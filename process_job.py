"""Run copied processing engines on the viewer's already-warm shared workers."""
import os,sys,threading,traceback
from PySide6 import QtCore as C
import bootstrap
import process_service

class SharedPool:
    def __init__(self,pool):self.pool=pool;self.workers=pool.workers
    def executor(self):
        self.pool.start();self.pool._ready.wait()
        if self.pool.state!='ready':raise RuntimeError(self.pool.error or 'Workers unavailable')
        return self.pool.executor
    def fail(self,exc):self.pool.state='failed';self.pool.error=str(exc)

class Output:
    def __init__(self,original,emit):self.original=original;self.emit=emit;self.thread=threading.get_ident()
    def write(self,text):
        # Engine origin-search threads also report progress here.
        self.emit(text);return len(text)
    def flush(self):pass
    def __getattr__(self,name):return getattr(self.original,name)

class ProcessJob(C.QThread):
    message=C.Signal(str)
    completed=C.Signal(dict)
    def __init__(self,request,pool,parent=None):super().__init__(parent);self.request=request;self.pool=pool
    def run(self):
        stdout,stderr=sys.stdout,sys.stderr;cwd=os.getcwd()
        try:
            from session_pool import install_session_pool
            install_session_pool(SharedPool(self.pool))
            sys.stdout=Output(stdout,self.message.emit);sys.stderr=Output(stderr,self.message.emit)
            self.message.emit(f'Using shared viewer pool: {self.pool.workers} workers ({self.pool.state})\n')
            self.request['workers']=self.pool.workers
            cache=process_service.run(self.request);self.completed.emit(dict(ok=True,stage=self.request['stage'],cache=cache))
        except Exception:
            self.message.emit(traceback.format_exc());self.completed.emit(dict(ok=False))
        finally:sys.stdout=stdout;sys.stderr=stderr;os.chdir(cwd)
