"""Undamped leave-one-out prediction fitting using unscaled pivoted QR in the physical SHE basis."""
import numpy as np
from scipy.linalg import qr, solve_triangular
from .utils import cartesian_to_spherical
from .she_solver_core import build_she_matrix


def basis(xyz, origin, order, k):
    coordinates = cartesian_to_spherical(*(np.asarray(xyz)-origin).T)
    matrix, actual_order = build_she_matrix(coordinates, order, k)
    if actual_order != order:
        raise ValueError('Requested harmonic order has nonfinite basis values.')
    return matrix


def prediction_fit(a, pressure):
    a = np.asarray(a, complex)
    p = np.asarray(pressure, complex)
    if a.ndim != 2 or p.shape != (len(a),) or len(a) <= a.shape[1]:
        raise ValueError('leave-one-out prediction requires more recordings than coefficients.')
    if not np.isfinite(a).all() or not np.isfinite(p).all() or not np.linalg.norm(p):
        raise ValueError('leave-one-out prediction needs finite basis values and nonzero pressure.')
    q, r, pivot = qr(a, mode='economic', pivoting=True, check_finite=False)
    diagonal = abs(np.diag(r))
    # Check independence relative to each column's units, without rescaling A.
    independence = diagonal/np.maximum(np.linalg.norm(a, axis=0)[pivot], 1e-300)
    rank = int(sum(independence > np.finfo(float).eps*max(a.shape)))
    if rank != a.shape[1]:
        raise ValueError('leave-one-out prediction basis is numerically dependent.')
    coeff = np.empty(a.shape[1], complex)
    coeff[pivot] = solve_triangular(r, q.conj().T@p, check_finite=False)
    residual = p-a@coeff
    denominator = 1-np.sum(abs(q)**2, axis=1)
    if denominator.min() <= 1e-10:
        raise ValueError('leave-one-out prediction deletion is not identifiable.')
    deleted = residual/denominator
    return coeff, dict(press_pct=float(100*np.linalg.norm(deleted)/np.linalg.norm(p)),
                      training_pct=float(100*np.linalg.norm(residual)/np.linalg.norm(p)),
                      residual=residual, loo_residual=deleted, rank=rank, columns=a.shape[1])
