"""Append classes.dex to an APK produced by aapt2 link.

Usage: python add_dex.py <base.apk> <classes.dex> <out.apk>
"""

import sys
import zipfile


def main() -> int:
    base, dex, out = sys.argv[1], sys.argv[2], sys.argv[3]
    with zipfile.ZipFile(base, "r") as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        if "classes.dex" not in src.namelist():
            dst.write(dex, "classes.dex")
    print("packed", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
