"""Portable end-of-scan LF recording QA. Requires only NumPy and SciPy.

No SHE, processed NPZ, driver locations, project origins, or fitted measurement
weights are read. Scanning is read-only; the review app can explicitly rename
confirmed exclusions and restore them without changing their contents.
"""
import argparse,csv,re,warnings
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly,find_peaks
from scipy.spatial import cKDTree

FREQUENCIES=40*2**(np.arange(37)/12)
BANDS=((40,80),(80,160),(160,321))
PATTERN=re.compile(r'.*_r(?P<r>-?\d+(?:p\d+)?)_ph(?P<p>-?\d+(?:p\d+)?)_z(?P<z>-?\d+(?:p\d+)?)(?:_.*)?\.wav$',re.I)


def coordinates(name):
    match=PATTERN.match(name)
    if not match:raise ValueError('Cannot parse cylindrical coordinates: '+name)
    radius,phi,z=(float(match[k].replace('p','.')) for k in ('r','p','z'))
    xyz=np.array([radius*np.cos(np.radians(phi)),radius*np.sin(np.radians(phi)),z])/1000
    return xyz,(radius,phi,z)


def features(path):
    """Read at most the first 0.35s and preserve physical inter-position phase."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',wavfile.WavFileWarning)
        try:fs,raw=wavfile.read(path,mmap=True)
        except ValueError as error:
            if 'mmap' not in str(error):raise
            fs,raw=wavfile.read(path,mmap=False)
    if raw.ndim!=1:raise ValueError('Expected mono IR')
    signal=np.asarray(raw[:int(.35*fs)],dtype=float)
    if raw.dtype == np.uint8:
        signal = (signal-128)/128
    elif np.issubdtype(raw.dtype,np.integer):
        signal/=float(np.iinfo(raw.dtype).max)+1
    if len(signal)<int(.05*fs) or not np.isfinite(signal).all() or not np.any(signal) or np.ptp(signal)==0:raise ValueError('Short, nonfinite, silent, or constant leading IR')
    early=abs(signal[:int(.1*fs)]);peaks,_=find_peaks(early,height=max(early)*10**(-12/20),distance=max(1,int(.0005*fs)))
    peak=int(peaks[0]) if len(peaks) else int(np.argmax(early));arrival=peak/fs
    # Common captures use 48 or 96kHz. A general rational conversion remains
    # available without loading an entire multi-second IR into memory.
    gcd=np.gcd(int(fs),4000);down=resample_poly(signal,4000//gcd,int(fs)//gcd);rate=4000
    begin=int(arrival*rate);end=min(len(down),begin+int(.2*rate));windowed=down.copy()
    if end-begin<2:raise ValueError('No usable post-arrival window')
    windowed[begin:end]*=.5*(1+np.cos(np.linspace(0,np.pi,end-begin)));windowed[end:]=0
    spectrum=np.fft.rfft(windowed,n=16384);ff=np.fft.rfftfreq(16384,1/rate)
    result=np.interp(FREQUENCIES,ff,spectrum.real)+1j*np.interp(FREQUENCIES,ff,spectrum.imag)
    return result*(fs/rate),dict(fs=int(fs),arrival_ms=1000*arrival,original_samples=len(raw),leading_samples_read=len(signal))


def robust_predict(xyz,response,index,near,*,trials=32):
    """Small local affine predictor with trimmed-subset initialization and IRLS."""
    dx=xyz[near]-xyz[index];scale=max(float(np.median(np.linalg.norm(dx,axis=1))),1e-9)
    _,s,vh=np.linalg.svd(dx-dx.mean(axis=0),full_matrices=False)
    dimension=int(np.count_nonzero(s>s[0]*.08));dimension=max(1,min(3,dimension))
    x=np.column_stack((np.ones(len(near)),dx@vh[:dimension].T/scale));y=response[near]
    distance=np.linalg.norm(dx,axis=1)/scale;spatial=1/(1+distance**2)
    subset_size=min(len(near),max(dimension+3,6));rng=np.random.default_rng(491)
    subsets=np.array([rng.choice(len(near),subset_size,replace=False) for _ in range(trials)])
    inverse=np.linalg.pinv(x[subsets],rcond=1e-5);coefficients=inverse@y[subsets]
    predicted=np.einsum('md,rdf->rmf',x,coefficients);residual=np.sqrt(np.mean(abs(predicted-y[None,:,:])**2,axis=2))
    trim=max(dimension+2,int(.7*len(near)));scores=np.mean(np.partition(residual**2,trim-1,axis=1)[:,:trim],axis=1)
    coeff=coefficients[int(np.argmin(scores))];typical=max(float(np.median(np.sqrt(np.mean(abs(y)**2,axis=1)))),1e-30)
    weights=spatial.copy()
    for iteration in range(8):
        error=np.sqrt(np.mean(abs(y-x@coeff)**2,axis=1));delta=max(3*float(np.median(error)),.001*typical)
        weights=spatial*np.minimum(1,delta/np.maximum(error,1e-30));root=np.sqrt(weights)
        coeff=np.linalg.lstsq(x*root[:,None],y*root[:,None],rcond=1e-5)[0]
    inverse=np.linalg.pinv(x*root[:,None],rcond=1e-5);h=np.sum((x*root[:,None])*inverse.T,axis=1)
    deleted=np.sqrt(np.mean(abs(y-x@coeff)**2,axis=1))/np.maximum(1-h,.05)
    trustworthy=weights/spatial>.5
    noise=float(np.median(deleted[trustworthy])) if trustworthy.any() else float(np.median(deleted))
    prediction_gain=float(np.linalg.norm(inverse[0]))
    return coeff[0],typical,noise,prediction_gain,dict(neighbours=len(near),dimension=dimension,downweighted_neighbours=int(sum(~trustworthy)),radius_m=float(max(np.linalg.norm(dx,axis=1))))


def inspect_point(xyz,response,index,neighbours,relative_floor=.10,noise_factor=8.):
    results=[]
    for low,high in BANDS:
        band=(FREQUENCIES>=low-1e-8)&(FREQUENCIES<high-1e-8);local=[]
        for count in (12,24):
            near=neighbours[index,1:count+1]
            prediction,typical,noise,gain,details=robust_predict(xyz,response[:,band],index,near)
            error=float(np.sqrt(np.mean(abs(response[index,band]-prediction)**2)))
            threshold=max(relative_floor*typical,noise_factor*noise*np.sqrt(1+gain*gain))
            local.append(dict(score=error/max(threshold,1e-30),relative_error_pct=100*error/typical,typical_local_error_pct=100*noise/typical,**details))
        results.append(dict(low_hz=low,high_hz=min(high,320),consensus_score=min(item['score'] for item in local),maximum_score=max(item['score'] for item in local),checks=local))
    strongest=max(results,key=lambda item:item['consensus_score']);one=max(item['maximum_score'] for item in results)
    status='repeat' if strongest['consensus_score']>1 else ('review' if one>1 else 'pass')
    if status=='review':strongest=max(results,key=lambda item:item['maximum_score'])
    return dict(status=status,score=strongest['consensus_score'],band_low_hz=strongest['low_hz'],band_high_hz=strongest['high_hz'],bands=results)


def inspect_all(xyz,response,relative_floor=.10,noise_factor=8.):
    if len(np.unique(np.round(xyz,9),axis=0))!=len(xyz):raise ValueError('Expected one IR per coordinate; compare repeat attempts separately')
    if len(xyz)<25:return [dict(status='insufficient_neighbours',score=0.,band_low_hz=40,band_high_hz=320,bands=[]) for _ in range(len(xyz))]
    _,near=cKDTree(xyz).query(xyz,k=25)
    return [inspect_point(xyz,response,i,near,relative_floor,noise_factor) for i in range(len(xyz))]


def scan_directory(folder, progress=lambda phase, done, total: None, cancelled=lambda: False):
    """Read-only scan; return review rows and compact data for inspection plots."""
    folder = Path(folder).resolve(strict=True)
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.name.lower().endswith('_ir.wav'))
    excluded_files = sorted(p for p in folder.iterdir() if p.is_file() and p.name.lower().endswith('_ir.wav.blacklisted'))
    if not files and not excluded_files:
        raise ValueError('No active *_ir.wav recordings found in this directory.')
    rows, valid = [], []
    for i, path in enumerate(files):
        if cancelled():
            raise InterruptedError('Scan cancelled.')
        row = dict(filename=path.name, status='technical', score=0., reason='', marked=False)
        try:
            row['identity'] = file_identity(path)
            xyz, cylindrical = coordinates(path.name)
            response, metadata = features(path)
            row.update(xyz=xyz, cylindrical=cylindrical, response=response, **metadata)
            valid.append(row)
        except (ValueError, OSError, EOFError) as error:
            row['reason'] = str(error)
        rows.append(row)
        progress('Reading IRs', i+1, len(files))
    groups = {}
    for row in valid:
        groups.setdefault(tuple(np.round(row['xyz'], 9)), []).append(row)
    for group in groups.values():
        if len(group) > 1:
            for row in group:
                row['reason'] = 'Duplicate coordinate; compare capture attempts separately.'
    valid = [row for row in valid if not row['reason']]
    if valid:
        xyz = np.array([row['xyz'] for row in valid])
        response = np.array([row['response'] for row in valid])
        near = cKDTree(xyz).query(xyz, k=min(25, len(valid)))[1] if len(valid) >= 25 else None
        for i, row in enumerate(valid):
            if cancelled():
                raise InterruptedError('Scan cancelled.')
            if near is None:
                row.update(status='insufficient_neighbours', score=0., bands=[], reason='At least 25 unique valid positions are required.')
            else:
                row.update(inspect_point(xyz, response, i, near))
                row['neighbours'] = [valid[j]['filename'] for j in near[i, 1:25]]
            progress('Comparing neighbours', i+1, len(valid))
    for path in excluded_files:
        rows.append(dict(filename=path.name, status='excluded', score=0., reason='Renamed; ignored by WAV processing.', marked=False, identity=file_identity(path)))
    rank = {'technical': 0, 'repeat': 1, 'review': 2, 'insufficient_neighbours': 3, 'pass': 4, 'excluded': 5}
    rows.sort(key=lambda row: (rank[row['status']], -row['score'], row['filename']))
    return rows


def file_identity(path):
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def rename_reviewed(folder, rows, restore=False):
    """Rename only explicitly reviewed files; preflight the whole batch and roll back failures."""
    folder = Path(folder).resolve(strict=True)
    plans = []
    for row in rows:
        name = row['filename']
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('Expected a filename inside the selected directory.')
        source = folder/name
        if source.is_symlink() or source.resolve().parent != folder:
            raise ValueError('Cannot rename a link or a file outside the selected directory.')
        if file_identity(source) != tuple(row['identity']):
            raise ValueError(f'{name} changed since review. Rescan before renaming.')
        if restore:
            if not name.lower().endswith('_ir.wav.blacklisted'):
                raise ValueError('Only excluded IRs can be restored.')
            destination = folder/name[:-len('.blacklisted')]
        else:
            if not name.lower().endswith('_ir.wav'):
                raise ValueError('Only active IR WAVs can be excluded.')
            destination = folder/(name+'.blacklisted')
        if destination.exists():
            raise FileExistsError(f'Will not overwrite {destination.name}.')
        plans.append((source, destination))
    if len({src for src, _ in plans}) != len(plans):
        raise ValueError('A file was selected more than once.')
    done = []
    try:
        for source, destination in plans:
            if destination.exists():
                raise FileExistsError(f'Will not overwrite {destination.name}.')
            source.rename(destination)
            done.append((source, destination))
    except OSError as error:
        failures = []
        for source, destination in reversed(done):
            try:
                if source.exists():
                    raise FileExistsError(source)
                destination.rename(source)
            except OSError:
                failures.append(destination.name)
        if failures:
            raise OSError(f'{error}; could not restore these renamed files: {failures}') from error
        raise
    return [destination.name for _, destination in done]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ir_folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = scan_directory(args.ir_folder)
    args.output.mkdir(parents=True, exist_ok=True)
    columns = ['filename', 'status', 'score', 'band_low_hz', 'band_high_hz', 'reason']
    with (args.output/'recording_quality.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    suspects = [row['filename'] for row in rows if row['status'] in ('repeat', 'technical')]
    (args.output/'blacklist_candidates.txt').write_text(''.join(name+'\n' for name in suspects), encoding='utf-8')
    print(f'{len(rows)} recordings; {len(suspects)} candidates. No input files renamed.')


if __name__ == '__main__':
    main()
