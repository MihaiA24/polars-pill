import polars as pl

from polars_sha import pig_latinnify


def test_piglatinnify():
    df = pl.DataFrame({"english": ["this", "is", "not", "pig", "latin", "éclair", "中文", "🙂", "", None]})
    result = df.with_columns(pig_latin=pig_latinnify("english"))

    expected_df = pl.DataFrame(
        {
            "english": ["this", "is", "not", "pig", "latin", "éclair", "中文", "🙂", "", None],
            "pig_latin": ["histay", "siay", "otnay", "igpay", "atinlay", "clairéay", "文中ay", "🙂ay", "", None],
        }
    )

    assert result.equals(expected_df)
