"""Shared pytest fixtures. All generated data goes to temporary folders."""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import generate_data  # noqa: E402

SMALL_REFERRAL_COUNT = 5_000
SMALL_SEED = 42


def read_tables(folder):
    """Read every generated CSV as text; empty fields become missing values."""
    return {
        name: pd.read_csv(Path(folder) / file_name, dtype=str,
                          keep_default_na=False, na_values=[""])
        for name, file_name in generate_data.OUTPUT_FILES.items()
    }


@pytest.fixture(scope="session")
def small_dataset_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("raw_small")
    generate_data.generate_dataset(SMALL_REFERRAL_COUNT, SMALL_SEED, folder)
    return folder


@pytest.fixture(scope="session")
def tables(small_dataset_dir):
    return read_tables(small_dataset_dir)


@pytest.fixture(scope="session")
def canonical_referrals(tables):
    """One row per business referral_id (first occurrence)."""
    return tables["referrals"].drop_duplicates("referral_id", keep="first")
