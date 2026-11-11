"""Shared numerical basis for fitting, condition checks and reconstruction."""
import numpy as np
from scipy.special import spherical_jn, sph_harm_y_all
from .utils import hankel2


def build_field_matrix(coords_sph, order_N, k, field="total"):
    """Evaluate the common acoustic basis; columns follow coefficient order."""
    internal = field.lower() == "internal"
    external = field.lower() == "external"
    r, th, ph = coords_sph
    kr = r * k
    # Evaluate angular terms together; origin searches call this shared builder often.
    harmonics = sph_harm_y_all(order_N, order_N, th, ph)
    # Build Matrix
    A_cols = []
    final_N = order_N
    for n in range(order_N + 1):
        hn = None if external else hankel2(n, kr)
        jn = None if internal else spherical_jn(n, kr)
        if any(value is not None and not np.all(np.isfinite(value)) for value in (hn, jn)):
            final_N = n - 1
            break
        for m_ord in range(-n, n + 1):
            Y = harmonics[n, m_ord]
            if not external:
                A_cols.append(hn * Y)
            if not internal:
                A_cols.append(jn * Y)

    return (np.column_stack(A_cols) if A_cols else np.empty((len(r), 0), complex)), final_N

