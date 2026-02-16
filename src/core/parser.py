import re

class HinglishParser:
  """Handles normalization and Hinglish amount parsing"""
  base_numbers = {
    'ek': 1, 'do': 2, 'teen': 3, 'char': 4, 'panch': 5,
    'paanch': 5, 'chhe': 6, 'saat': 7, 'aath': 8, 'nau': 9,
    'dus': 10, 'bees': 20, 'tees': 30, 'chalis': 40, 'pachas': 50,
    'saath': 60, 'sattar': 70, 'assi': 80, 'nabbe': 90
  }
  multipliers = {
    'sau': 100,
    'hazar': 1000,
    'hazaar': 1000
  }
  hindi_words = set(['ek', 'do', 'teen', 'char', 'panch', 'paanch', 'chhe',
    'saat', 'aath', 'nau', 'dus', 'sau', 'hazar', 'hazaar'])
  word_mappings = {
    'petol': 'petrol',
    'dhoodh': 'milk',
    'dudh': 'milk',
    'kirana': 'grocery'
  }
  hindi_numbers = {
    'ek': '1', 'do': '2', 'teen': '3', 'char': '4', 'panch': '5',
    'paanch': '5', 'chhe': '6', 'saat': '7', 'aath': '8', 
    'nau': '9', 'dus': '10'
  }

  @staticmethod
  def normalize_input(text):
    text = text.lower().strip()
    words = text.split()
    normalized_words = []
    for word in words:
      if word in HinglishParser.hindi_numbers:
        normalized_words.append(HinglishParser.hindi_numbers[word])
      elif word in HinglishParser.word_mappings:
        normalized_words.append(HinglishParser.word_mappings[word])
      else:
        normalized_words.append(word)
    return ' '.join(normalized_words)

  @staticmethod
  def parse_hinglish_amount(text):
    words = text.lower().strip().split()
    total = 0
    current_num = 0
    amount_words_count = 0
    for i, word in enumerate(words):
      if word in HinglishParser.base_numbers:
        current_num = HinglishParser.base_numbers[word]
        amount_words_count = i + 1
      elif word in HinglishParser.multipliers:
        if current_num == 0:
          current_num = 1
        total += current_num * HinglishParser.multipliers[word]
        current_num = 0
        amount_words_count = i + 1
      else:
        try:
          num = float(word)
          if current_num == 0:
            current_num = num
          else:
            total += current_num
            current_num = num
          amount_words_count = i + 1
        except ValueError:
          break
    if current_num > 0:
      total += current_num
    remaining_text = ' '.join(words[amount_words_count:]).strip()
    return (total if total > 0 else None, remaining_text)

  @staticmethod
  def highlight(text, keyword):
    return re.sub(f'({re.escape(keyword)})', r'**\1**', text, flags=re.IGNORECASE)
