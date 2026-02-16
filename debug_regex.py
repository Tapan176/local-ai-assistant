import re

text = "shopping at AlphaOne 2,500"
nums = re.findall(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', text)
print(f"Nums: {nums}")
if nums:
    val_str = nums[-1].replace(',', '')
    val = float(val_str)
    print(f"Val: {val}")
else:
    print("No nums found")
