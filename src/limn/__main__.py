"""`python -m limn`: the same as the `limn` command (limn.cli.main); its return value is the exit status."""

from limn.cli import main

raise SystemExit(main())
