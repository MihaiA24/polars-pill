import hashlib

import polars as pl
from polars.testing import assert_frame_equal

from polars_sha import sha2_256, sha2_512


def test_sha2_matches_hashlib() -> None:
    values = ["", None, "abc", "éclair", "中文", "🙂", "e\u0301", None]
    multichunk = pl.concat(
        [pl.Series("value", values[:4], dtype=pl.String), pl.Series("value", values[4:], dtype=pl.String)],
        rechunk=False,
    )
    assert multichunk.n_chunks() == 2

    for source in (pl.Series("value", [], dtype=pl.String), multichunk, multichunk.slice(1, 6)):
        frame = source.to_frame()
        for plugin, digest in ((sha2_256, hashlib.sha256), (sha2_512, hashlib.sha512)):
            expected = pl.DataFrame(
                {
                    "hash": pl.Series(
                        [None if value is None else digest(value.encode("utf-8")).hexdigest() for value in source],
                        dtype=pl.String,
                    )
                }
            )
            expression = plugin("value").alias("hash")
            assert_frame_equal(frame.select(expression), expected)
            assert_frame_equal(frame.lazy().select(expression).collect(engine="streaming"), expected)
