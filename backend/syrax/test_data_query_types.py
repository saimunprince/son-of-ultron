"""Live 2026-11-06: "the coldest city" in a CSV came out as Tokyo 18 instead of Oslo 4: the columns were text, so
ORDER BY sorted "18" < "31" < "4". Columns of numbers are numbers now; leading zeros keep a column text."""

from syrax.data_query import query


def test_numbers_sort_as_numbers(tmp_path):
    p = tmp_path / "temps.csv"
    p.write_text("city,temp,rain\nDhaka,31,2.5\nTokyo,18,10\nOslo,4,0.75\n")
    assert query(str(p), "SELECT city FROM data ORDER BY temp ASC LIMIT 1").splitlines()[1] == "Oslo"
    assert query(str(p), "SELECT city FROM data ORDER BY rain DESC LIMIT 1").splitlines()[1] == "Tokyo"
    assert query(str(p), "SELECT SUM(temp) FROM data").splitlines()[1] == "53"


def test_leading_zeros_and_text_stay_text(tmp_path):
    p = tmp_path / "people.csv"
    p.write_text("name,zip,phone,note\nAna,01234,0171000,x\nBo,98765,0181000,7\nCy,,0191000,\n")
    out = query(str(p), "SELECT zip, phone FROM data WHERE name = 'Ana'")
    assert out.splitlines()[1] == "01234 | 0171000"
    assert query(str(p), "SELECT COUNT(*) FROM data WHERE zip IS NULL").splitlines()[1] == "1"
