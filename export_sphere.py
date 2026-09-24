"""Reconstruct a portable complex sphere without opening the viewer."""
import argparse
from pathlib import Path
import bootstrap
from acoustics import reconstruct, save_sphere


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coefficients", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--radius", type=float, default=2.)
    parser.add_argument("--step", type=int, choices=[2, 3, 5, 6, 10, 15], default=5)
    parser.add_argument("--bins", type=int, default=480, help="Log targets snapped to unique native bins; 0 = all bins")
    parser.add_argument("--fmin", type=float, default=20.)
    parser.add_argument("--fmax", type=float, default=20000.)
    parser.add_argument("--mode", choices=["Internal", "External", "Total"], default="Internal")
    parser.add_argument("--padding", type=int, default=50)
    parser.add_argument("--offset", nargs=3, type=float, default=(0., 0., 0.), metavar=("X", "Y", "Z"))
    parser.add_argument("--fixed-origin", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists. Choose a new filename.")
    if args.output.suffix.lower() != ".npz":
        parser.error("Output must end in .npz")
    if args.bins < 0 or args.bins == 1 or args.padding < 0 or args.fmin >= args.fmax:
        parser.error("Use bins=0 or bins>=2, nonnegative padding, and fmin<fmax.")
    sphere = reconstruct(args.coefficients, step=args.step, bins=args.bins, radius=args.radius,
                         mode=args.mode, fmin=args.fmin, fmax=args.fmax, padding=args.padding,
                         origins=not args.fixed_origin, offset=args.offset,
                         progress=lambda percent, message: print(f"\r{percent:3d}%  {message}", end="", flush=True))
    save_sphere(sphere, args.output)
    print(f"\nSaved {args.output} · {sphere.pressure.shape} complex samples")


if __name__ == "__main__":
    main()
