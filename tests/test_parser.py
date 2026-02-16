from src.core.parser import HinglishParser

def test_hinglish_amount():
    parser = HinglishParser()
    cases = [
        ("do sau petrol", 200, "petrol"),
        ("teen sau food", 300, "food"),
        ("panch sau doodh", 500, "doodh"),
        ("ek hazar rent", 1000, "rent"),
        ("teen sau pachas misc", 350, "misc"),
        ("do hazar entertainment", 2000, "entertainment"),
        ("200 electricity", 200, "electricity")
    ]
    for text, exp_amt, exp_cat in cases:
        amt, rem = parser.parse_hinglish_amount(text)
        cat = rem.split()[0] if rem else 'misc'
        assert amt == exp_amt, f"{text}: got {amt}, expected {exp_amt}"
        assert cat == exp_cat, f"{text}: got {cat}, expected {exp_cat}"

def test_normalize():
    parser = HinglishParser()
    assert parser.normalize_input("petol") == "petrol"
    assert parser.normalize_input("dhoodh") == "milk"
    assert parser.normalize_input("ek sau petrol") == "1 sau petrol"
