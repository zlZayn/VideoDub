"""FunASR 适配器 — paraformer-zh + fsmn-vad，中文推荐

行为与旧 core/speech_recognizer.recognize_with_funasr 保持一致；
输出改为统一 Transcript 模型。
"""

from __future__ import annotations

import itertools
from collections import Counter

from videodub.domain.transcript import Transcript
from videodub.utils.logger import log, log_stage_header, log_warning

# 句内标点（无对应时间戳，切分对齐时跳过）
_PUNCT_CHARS = set("，。！？；：、,.!?;:…—·～ “”‘’\"'（）()《》【】\u3000")


def _split_segments_by_silence(
    segments: list[dict], timestamps, threshold_ms: int
) -> list[dict]:
    """用字级时间戳在句内静音处进一步切分（说话人继承）。

    对齐策略：句窗口 [start, end] 内的时间戳数与句文本非标点字符数一致时才切
    （1 字 1 时间戳），不一致则该句保持原样，宁可漏切不可错切。
    """
    if not timestamps:
        return segments
    result: list[dict] = []
    for seg in segments:
        start_ms, end_ms = seg["start"] * 1000, seg["end"] * 1000
        window = [t for t in timestamps if t[0] < end_ms and t[1] > start_ms]
        text = seg["text"]
        char_ts = []  # (text 位置, 时间戳)，非标点字符
        idx = 0
        for pos, ch in enumerate(text):
            if ch in _PUNCT_CHARS:
                continue
            if idx < len(window):
                char_ts.append((pos, window[idx]))
            idx += 1
        if len(char_ts) != idx or len(char_ts) < 2:
            result.append(seg)  # 时间戳数与字符数不一致（或太短），不切
            continue
        # 静音 >= 阈值处切：切点为该字符的 text 位置（其前标点归左侧）
        cuts = [0]
        for k in range(1, len(char_ts)):
            gap = char_ts[k][1][0] - char_ts[k - 1][1][1]
            if gap >= threshold_ms:
                cuts.append(char_ts[k][0])
        cuts.append(len(text))
        pieces = []
        for b0, b1 in itertools.pairwise(cuts):
            piece_text = text[b0:b1].strip()
            if not piece_text:
                continue
            ts_in = [t for pos, t in char_ts if b0 <= pos < b1]
            piece = dict(seg)
            piece["text"] = piece_text
            piece["start"] = ts_in[0][0] / 1000.0
            piece["end"] = ts_in[-1][1] / 1000.0
            pieces.append(piece)
        result.extend(pieces if pieces else [seg])
    return result


class FunAsrTranscriber:
    """FunASR 语音识别（中文）+ 可选 CAM++ 说话人分离"""

    backend = "funasr"

    def __init__(
        self,
        model_name: str = "paraformer-zh",
        vad_model_name: str = "fsmn-vad",
        device: str = "cpu",
        min_silence_ms: int = 300,
        enable_diarization: bool = False,
        max_speakers: int = 2,
        speaker_embedding_model: str = "cam++",
        split_silence_ms: int = 200,
    ) -> None:
        self.model_name = model_name
        self.vad_model_name = vad_model_name
        self.device = device
        self.min_silence_ms = min_silence_ms
        self.enable_diarization = enable_diarization
        self.max_speakers = max_speakers
        self.speaker_embedding_model = speaker_embedding_model
        self.split_silence_ms = split_silence_ms

    def transcribe(self, audio_path: str) -> Transcript:
        """识别音频，返回统一 Transcript"""
        from funasr import AutoModel

        diarization_desc = (
            f" + {self.speaker_embedding_model}说话人分离(最多{self.max_speakers}人)"
            if self.enable_diarization
            else ""
        )
        log_stage_header(
            "ASR",
            f"FunASR ({self.model_name} + {self.vad_model_name}{diarization_desc}), 设备: {self.device}",
        )

        log("ASR", "加载模型 ...")
        model_kwargs = {
            "model": self.model_name,
            "model_revision": "v2.0.4",
            "vad_model": self.vad_model_name,
            "vad_model_revision": "v2.0.4",
            "device": self.device,
        }
        if self.enable_diarization:
            model_kwargs["punc_model"] = "ct-punc"
            model_kwargs["spk_model"] = self.speaker_embedding_model
            # 此版本 FunASR 不再接受 spk_kwargs["max_num_speakers"]；
            # 期望说话人数在 generate() 用 preset_spk_num（聚类 oracle）指定
        model = AutoModel(**model_kwargs)

        log("ASR", "识别中 ...")
        generate_kwargs: dict = {"input": audio_path, "batch_size_s": 300, "cache": {}}
        if self.enable_diarization:
            generate_kwargs["preset_spk_num"] = self.max_speakers
        results = model.generate(**generate_kwargs)

        if not results or len(results) == 0:
            log_warning("未识别到语音内容")
            return Transcript(source="funasr")

        result = results[0]

        # 启用说话人分离：直接用 sentence_info（含 spk 标签）
        if self.enable_diarization and result.get("sentence_info"):
            segments = []
            for seg in result["sentence_info"]:
                text = seg.get("sentence", seg.get("text", "")).strip()
                if not text:
                    continue
                segments.append(
                    {
                        "start": seg.get("start", 0) / 1000.0,
                        "end": seg.get("end", 0) / 1000.0,
                        "text": text,
                        "speaker": seg.get("spk", 0),
                    }
                )
            # 快语速下标点断句会并句：再用字级时间戳在句内明显静音处细切（碎句交给 label 人工合并/修标点）
            segments = _split_segments_by_silence(
                segments, result.get("timestamp"), self.split_silence_ms
            )
            spk_counts = Counter(seg["speaker"] for seg in segments)
            log("ASR", f"识别到 {len(segments)} 句台词，{len(spk_counts)} 个说话人:")
            for seg in segments:
                log(
                    "ASR",
                    f"  [{seg['start']:6.2f}s - {seg['end']:6.2f}s] 说话人{seg['speaker']}: {seg['text']}",
                )
            log("ASR", f"说话人统计: {dict(spk_counts)}")
            return Transcript.from_dicts(segments, source="funasr")

        # 未启用说话人分离：用词级时间戳按停顿分段
        chars = result["text"].split()
        timestamps = result.get("timestamp", [])

        if not timestamps or len(timestamps) != len(chars):
            full_text = "".join(chars)
            log("ASR", f"识别到 1 句台词: {full_text}")
            return Transcript.from_dicts(
                [{"start": 0.0, "end": 0.0, "text": full_text}], source="funasr"
            )

        segments = []
        current_start_idx = 0
        for i in range(1, len(chars)):
            gap = timestamps[i][0] - timestamps[i - 1][1]
            if gap > self.min_silence_ms:
                segments.append(
                    {
                        "start": timestamps[current_start_idx][0] / 1000.0,
                        "end": timestamps[i - 1][1] / 1000.0,
                        "text": "".join(chars[current_start_idx:i]),
                    }
                )
                current_start_idx = i

        if current_start_idx < len(chars):
            segments.append(
                {
                    "start": timestamps[current_start_idx][0] / 1000.0,
                    "end": timestamps[-1][1] / 1000.0,
                    "text": "".join(chars[current_start_idx:]),
                }
            )

        log("ASR", f"识别到 {len(segments)} 句台词:")
        for seg in segments:
            log("ASR", f"  [{seg['start']:6.2f}s - {seg['end']:6.2f}s] {seg['text']}")
        return Transcript.from_dicts(segments, source="funasr")
