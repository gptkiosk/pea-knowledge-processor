# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""PEA knowledge processor: a curated list of sources in, one fixed and validated format out."""

__version__ = "0.4.0"

GENERATOR_NAME = "pea-knowledge-processor"
REPOSITORY_URL = "https://github.com/gptkiosk/pea-knowledge-processor"

# The format this code writes and the newest one it reads. A reader accepts every file whose major it knows.
FORMAT_MAJOR = 1
FORMAT_MINOR = 2
FORMAT_VERSION = "%d.%d" % (FORMAT_MAJOR, FORMAT_MINOR)
