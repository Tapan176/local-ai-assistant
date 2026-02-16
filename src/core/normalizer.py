"""
Normalizer - Handles text normalization and word mappings
"""

class Normalizer:
    """Normalizes user input for better parsing"""
    
    # Hindi number word mappings
    hindi_numbers = {
        'ek': '1', 'do': '2', 'teen': '3', 'char': '4', 'panch': '5',
        'paanch': '5', 'chhe': '6', 'saat': '7', 'aath': '8', 
        'nau': '9', 'dus': '10'
    }
    
    # Common word normalizations
    word_mappings = {
        'petol': 'petrol',
        'dhoodh': 'milk',
        'dudh': 'milk',
        'kirana': 'grocery',
        'bijli': 'electricity',
        'paani': 'water'
    }
    
    @staticmethod
    def normalize(text):
        """Normalize user input
        
        Args:
            text: Raw user input
            
        Returns:
            Normalized text with Hindi numbers and common words converted
        """
        text = text.lower().strip()
        words = text.split()
        normalized_words = []
        
        for word in words:
            if word in Normalizer.hindi_numbers:
                normalized_words.append(Normalizer.hindi_numbers[word])
            elif word in Normalizer.word_mappings:
                normalized_words.append(Normalizer.word_mappings[word])
            else:
                normalized_words.append(word)
        
        return ' '.join(normalized_words)
