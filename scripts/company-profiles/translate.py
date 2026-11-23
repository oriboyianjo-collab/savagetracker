"""Offline English-to-Hebrew translation. No paid APIs, no network at translate time
once the model is cached. Argos Translate first, Helsinki opus-mt-en-he as fallback.
"""
from __future__ import annotations

import os
import sys


class Translator:
    def __init__(self):
        self.backend = None
        self._fn = None

    def load(self):
        if self._fn:
            return self.backend
        err = []
        try:
            self._load_argos()
            return self.backend
        except Exception as e:
            err.append(f"argos: {e}")
        try:
            self._load_opus()
            return self.backend
        except Exception as e:
            err.append(f"opus-mt: {e}")
        raise RuntimeError("no offline translator available: " + "; ".join(err))

    def _load_argos(self):
        import argostranslate.package
        import argostranslate.translate

        installed = argostranslate.translate.get_installed_languages()
        en = next((l for l in installed if l.code == "en"), None)
        he = next((l for l in installed if l.code == "he"), None)
        if not (en and he):
            # Install from a local package dir if provided (CI caches this).
            pkg_dir = os.environ.get("ARGOS_PACKAGE_DIR", "")
            if pkg_dir and os.path.isdir(pkg_dir):
                for name in os.listdir(pkg_dir):
                    if name.endswith(".argosmodel"):
                        argostranslate.package.install_from_path(os.path.join(pkg_dir, name))
                installed = argostranslate.translate.get_installed_languages()
                en = next((l for l in installed if l.code == "en"), None)
                he = next((l for l in installed if l.code == "he"), None)
        if not (en and he):
            raise RuntimeError("en-he package not installed")
        tr = en.get_translation(he)
        if tr is None:
            raise RuntimeError("no en->he translation")
        self._fn = tr.translate
        self.backend = "argos"

    def _load_opus(self):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline

        model_id = os.environ.get("OPUS_MODEL", "Helsinki-NLP/opus-mt-en-he")
        cache = os.environ.get("HF_HOME") or os.environ.get("TRANSFORMERS_CACHE")
        tok = AutoTokenizer.from_pretrained(model_id, cache_dir=cache)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache)
        pipe = pipeline("translation", model=model, tokenizer=tok, src_lang=None)
        def fn(text):
            out = pipe(text, max_length=max(64, min(1024, len(text.split()) * 4)))
            if isinstance(out, list):
                return out[0]["translation_text"]
            return out["translation_text"]
        self._fn = fn
        self.backend = "opus-mt-en-he"

    def translate(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        if not self._fn:
            self.load()
        return (self._fn(text) or "").strip()
