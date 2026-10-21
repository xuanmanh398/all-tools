import random
import time
import string
from dataclasses import dataclass

@dataclass
class AntiSpamConfig:
    min_delay_sec: int = 45
    max_delay_sec: int = 120
    rest_after_posts: int = 5
    rest_duration_min: int = 10
    typing_speed_min_ms: int = 30
    typing_speed_max_ms: int = 100
    randomize_media: bool = True
    add_unique_hash: bool = False
    max_posts_per_day: int = 30

class AntiSpamManager:
    def __init__(self, config: AntiSpamConfig = None):
        self.config = config or AntiSpamConfig()
        self.posts_sent_session = 0

    def get_random_delay(self) -> int:
        """Lấy khoảng thời gian chờ ngẫu nhiên giữa 2 bài đăng (giây)."""
        return random.randint(self.config.min_delay_sec, self.config.max_delay_sec)

    get_post_delay = get_random_delay
    get_delay_seconds = get_random_delay

    def get_typing_delay(self) -> float:
        """Lấy khoảng thời gian nghỉ giữa mỗi phím gõ (giây)."""
        return random.uniform(self.config.typing_speed_min_ms / 1000.0, self.config.typing_speed_max_ms / 1000.0)

    def should_rest(self) -> bool:
        """Kiểm tra xem đã đến lúc tạm nghỉ bài đăng chưa."""
        if self.config.rest_after_posts <= 0:
            return False
        return (self.posts_sent_session > 0) and (self.posts_sent_session % self.config.rest_after_posts == 0)

    should_take_rest = should_rest

    @property
    def post_count(self) -> int:
        return self.posts_sent_session

    def get_rest_duration_sec(self) -> int:
        """Lấy thời gian nghỉ lớn tính bằng giây."""
        return self.config.rest_duration_min * 60

    def prepare_text(self, text: str) -> str:
        """Thêm mã hash / ký tự ngẫu nhiên vào cuối bài viết nếu được bật."""
        if self.config.add_unique_hash:
            random_hash = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
            text += f"\n\nRef: #{random_hash}"
        return text

    def prepare_media(self, media_paths: list[str]) -> list[str]:
        """Xáo trộn thứ tự hình ảnh/video nếu được cấu hình."""
        if not media_paths:
            return []
        copied = list(media_paths)
        if self.config.randomize_media:
            random.shuffle(copied)
        return copied

    def record_post(self):
        """Ghi nhận đã thực hiện 1 bài đăng."""
        self.posts_sent_session += 1
