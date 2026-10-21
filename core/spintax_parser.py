import re
import random

class SpintaxParser:
    """
    Parser cho chuỗi Spintax có hỗ trợ lồng nhau.
    Cú pháp: {Nội dung 1|Nội dung 2|{Con 1|Con 2}}
    """

    @staticmethod
    def parse(text: str) -> str:
        if not text:
            return ""

        pattern = re.compile(r'\{([^{}]+)\}')

        while True:
            match = pattern.search(text)
            if not match:
                break
            choices = match.group(1).split('|')
            chosen = random.choice(choices)
            text = text[:match.start()] + chosen + text[match.end():]

        return text

    @staticmethod
    def preview_variations(text: str, count: int = 5) -> list[str]:
        """Tạo danh sách các biến thể mẫu để xem trước."""
        variations = set()
        # Thử sinh tối đa count * 3 lần để lấy được số bản duy nhất
        for _ in range(count * 5):
            v = SpintaxParser.parse(text)
            variations.add(v)
            if len(variations) >= count:
                break
        return list(variations)


if __name__ == "__main__":
    test_str = "{Xin chào|Chào bạn|Hi} {anh/chị|mọi người}, hôm nay {rất đẹp trời|thời tiết tuyệt vời|ngày lành}! {Liên hệ ngay: {0901234567|0987654321}|Inbox trực tiếp}"
    print("Mẫu gốc:", test_str)
    print("\n--- 5 Biến thể mẫu ---")
    for idx, var in enumerate(SpintaxParser.preview_variations(test_str, 5), 1):
        print(f"{idx}. {var}")
