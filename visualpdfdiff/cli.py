import sys
from pathlib import Path
from consolemsg import fail
from .implementation import visualEqual, tmpchanges

usage = """\
Usage: {} <doc1.pdf> <doc2.pdf> [<diff.pdf>]

Returns 0 if there is no significant visual differences.
Returns 1 if the diferences are found.
Returns other number if an error happens.

If the third argument is provided a side by side diff
pdf is produced with the differences encircled in red.
"""


def main():
    if len(sys.argv) < 3:
        fail("Wrong arguments\n{}".format(usage))

    a, b = (Path(x) for x in sys.argv[1:3])
    output = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    tmpchanges("start")
    visualEqual(a, b, output)
    tmpchanges("end")


if __name__ == "__main__":
    main()
