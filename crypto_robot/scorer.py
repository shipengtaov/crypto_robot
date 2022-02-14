from .kline import KLine, KLineQueue


class Scorer:
    def __init__(self, kline_queue:KLineQueue, start_index:int, end_index:int):
        """
        Args:
            end_index: 包含 end_index
        """
        self.kline_queue = kline_queue
        self.start_index = start_index
        self.end_index = end_index
        assert start_index < end_index

    def get_score(self):
        kline_scores = [
            self._get_kline_score(self.kline_queue.queue[i]) for i in range(self.start_index, self.end_index+1)
        ]
        score = 100 * sum(kline_scores) / self.full_score
        return "{:.2f}".format(score)

    def _get_kline_score(self, kline:KLine) -> float:
        """
        >>> obj = Scorer(None, -5, -1)
        >>> obj._get_kline_score(KLine(open=1, close=2, high=4, low=0))
        0.25
        """
        kline_diff = abs(kline.close - kline.open)
        if kline_diff == 0:
            return 0.5

        up_diff = abs(kline.high - max(kline.open, kline.close))
        down_diff = abs(kline.low - min(kline.open, kline.close))

        total_diff = (up_diff + down_diff)/kline_diff
        return 1/(1+total_diff)

    @property
    def _max_kline_score(self):
        return 1

    @property
    def full_score(self):
        return self._max_kline_score * (abs(self.start_index - self.end_index) + 1)
