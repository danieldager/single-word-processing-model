import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import spacy
import spacy.cli
from g2p_en import G2p
from morphemes import Morphemes
from wordfreq import iter_wordlist, word_frequency, zipf_frequency

from .paths import get_dataset_dir


def process_dataset(directory: Path, real=False) -> pd.DataFrame:
    r"""Process the hand-made test datasets"""
    data = []
    for file in directory.glob("*.csv"):
        name_parts = file.stem.split("_")
        df = pd.read_csv(file)
        df["Lexicality"] = name_parts[1]
        df["Morphology"] = name_parts[-1]
        if real:
            df["Size"] = name_parts[3]
            df["Frequency"] = name_parts[2]
        else:
            df["Size"] = name_parts[2]
        data.append(df)

    data = pd.concat(data, join="outer")
    return data


def get_morphological_data(word: str):
    r"""Get morphological data for a word"""
    mrp = Morphemes(
        str(get_dataset_dir() / "morphemes_data")
    )  # TODO check that the path is ok
    parse = mrp.parse(word)

    if parse["status"] == "NOT_FOUND":
        return None, None, None, None, None, None

    tree = parse["tree"]
    prefixes, roots, root_freqs, suffixes = [], [], [], []

    for node in tree:
        if node["type"] == "prefix":
            prefixes.append(node["text"])

        elif "children" in node:
            for child in node["children"]:
                if child["type"] == "root":
                    roots.append(child["text"])
                    root_freqs.append(zipf_frequency(child["text"], "en"))
        else:
            suffixes.append(node["text"])

    count = parse["morpheme_count"]
    structure = f"{len(prefixes)}-{len(roots)}-{len(suffixes)}"

    return prefixes, roots, root_freqs, suffixes, count, structure


def clean_and_enrich_data(df: pd.DataFrame, real=False) -> pd.DataFrame:
    r"""Add frequency, part of speech, phonemes, and morphology to the dataset"""
    g2p = G2p()
    if not spacy.util.is_package("en_core_web_lg"):
        spacy.cli.download("en_core_web_lg")
    nlp = spacy.load("en_core_web_lg")
    # Drop rows with no word value
    df = df.dropna(subset=["word"])

    # Rename columns
    df = df.rename(
        columns={
            "word": "Word",
            "PoS": "Part of Speech",
            "num letters": "Length",
        }
    )

    # Add Zipf Frequency and Part of Speech columns
    if real:
        df = df.drop(columns=["Number", "percentile freq", "morph structure"])
        df["Zipf Frequency"] = df["Word"].apply(lambda x: zipf_frequency(x, "en"))
        df["Part of Speech"] = df["Word"].apply(lambda x: nlp(x)[0].pos_)

    # Add Phonemes column
    df["Phonemes"] = df["Word"].apply(g2p)

    # NOTE: Very slow
    # Add Morphological data
    # columns = ["Prefixes", "Roots", "Frequencies", "Suffixes", "Morpheme Count", "Structure"]
    # df[columns] = df['Word'].apply(lambda word: pd.Series(get_morphological_data(word)))

    return df


def get_test_data() -> tuple[pd.DataFrame, list[str]]:
    r"""Combine and reformat the real and pseudo word datasets"""
    # Process real words
    TEST_DATA_REAL = get_dataset_dir() / "handmade" / "test_dataset_real"
    TEST_DATA_PSEUDO = get_dataset_dir() / "handmade" / "test_dataset_pseudo"
    real_words = process_dataset(TEST_DATA_REAL, real=True)
    real_words = clean_and_enrich_data(real_words, real=True)

    # Process pseudo words
    pseudo_words = process_dataset(TEST_DATA_PSEUDO)
    pseudo_words = clean_and_enrich_data(pseudo_words)

    # Combine datasets
    dataframe = pd.concat(
        [real_words, pseudo_words], join="outer"
    )  # , ignore_index=True)

    # Rearrange columns
    columns = [
        "Word",
        "Size",
        "Length",
        "Frequency",
        "Zipf Frequency",
        "Morphology",
        "Lexicality",
        "Part of Speech",
        "Phonemes",
    ]
    dataframe = dataframe.reindex(columns=columns)

    # Isolate words and their phonemes
    real_words = real_words[["Word", "Phonemes"]]
    pseudo_words = pseudo_words[["Word", "Phonemes"]]

    return dataframe, real_words["Word"].tolist()


def sample_words(test_data: pd.DataFrame, word_count=50000, split=0.9, freq_th=0.95):
    g2p = G2p()
    word_list = []
    freq_list = []
    total_freq = 0

    test_words = test_data["Word"].tolist()
    for i, word in enumerate(iter_wordlist("en")):
        # Limit the number of words
        if i >= 30000:
            break
        # Skip any non-alphabetic words
        if not word.isalpha():
            continue
        # Skip any words in the test set
        if word in test_words:
            continue
        # Skip any words that don't have vowels
        if not any(char in "aeiou" for char in word):
            continue

        freq = word_frequency(word, "en")
        word_list.append(word)
        freq_list.append(freq)
        total_freq += freq

    # Normalize frequencies
    freq_array = np.array(freq_list) / total_freq

    # Sort words by frequency (low to high)
    sorted_indices = np.argsort(freq_array)
    sorted_freqs = freq_array[sorted_indices]
    sorted_words = [word_list[i] for i in sorted_indices]

    # Sample training words
    train_count = int(word_count * split)
    train_words = np.random.choice(sorted_words, train_count, p=sorted_freqs)

    # Sample validation words from low frequency words
    valid_count = word_count - train_count

    # Determine the index that separates low frequency words
    lf_index = np.searchsorted(np.cumsum(sorted_freqs), freq_th)

    # Sample validation words from low frequency candidate words
    candidates = [
        w for i, w in enumerate(sorted_words) if i < lf_index and w not in train_words
    ]
    valid_words = random.sample(candidates, min(valid_count, len(candidates)))

    # Get phonemes for each word
    train_phonemes = [g2p(word) for word in train_words]
    valid_phonemes = [g2p(word) for word in valid_words]

    # start = time.perf_counter()
    # print(f"{time.perf_counter() - start:.2f} seconds")
    return train_phonemes, valid_phonemes


def phoneme_statistics(phonemes: list):
    # Get the counts for each phoneme
    phoneme_stats = defaultdict(int)
    for word in phonemes:
        for phoneme in word:
            phoneme_stats[phoneme] += 1

    # Sort descending by count
    phoneme_stats = dict(
        sorted(phoneme_stats.items(), key=lambda x: x[1], reverse=True)
    )
    phoneme_stats["<STOP>"] = 0  # Add stop token

    # Get the bigram counts for each phoneme pair
    bigram_stats = defaultdict(int)
    for word in phonemes:
        for i in range(len(word) - 1):
            bigram = " ".join(word[i : i + 2])
            bigram_stats[bigram] += 1

    # trigram_stats = defaultdict(0)
    # for sequence in phonemes:
    #     for i in range(len(sequence) - 2):
    #         trigram = " ".join(sequence[i:i+3])
    #         trigram_stats[trigram] += 1

    return phoneme_stats, bigram_stats
