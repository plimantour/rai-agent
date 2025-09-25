
# Philippe Limantour - March 2024
# This file contains the functions to save and load the completions from the cache

import os
import pickle
import hashlib

# termcolor optional (test/lean env safety). Only attempt import once.
try:  # pragma: no cover - trivial import guard
    from termcolor import colored  # type: ignore
except ImportError:  # Fallback: silent no-color
    def colored(x, *args, **kwargs):  # type: ignore
        return x

def create_cache_folder_if_not_exists():
    """
    Create the cache folder if it does not exist.
    """
    if not os.path.exists('./cache/'):
        os.makedirs('./cache/')

def load_pickle(file):
    """
    Load the pickle file.

    Args:
        file (str): The path to the pickle file.

    Returns:
        The data loaded from the pickle file.
    """
    with open(file, 'rb') as f:
        data = pickle.load(f)
    return data

def save_pickle(data, file):
    """
    Save the data to a pickle file.

    Args:
        data: The data to be saved.
        file (str): The path to the pickle file.
    """
    with open(file, 'wb') as f:
        pickle.dump(data, f)

def create_unique_identifier(question):
    """
    Create a unique identifier for the question.

    Args:
        question (str): The question text.

    Returns:
        str: The unique identifier generated using MD5 hash.
    """
    question_bytes = question.encode('utf-8')
    identifier = hashlib.md5(question_bytes).hexdigest()
    return identifier

def save_completion_to_cache(question, answer):
    """
    Save the completion to the cache.

    Args:
        question (str): The question text.
        answer: The completion answer.

    Returns:
        str: The unique identifier for the question.
    """
    create_cache_folder_if_not_exists()
    question_key = create_unique_identifier(question)
    print(colored(f"Saving completion to cache for question: {question_key}", "cyan"))
    data = {
        question_key : answer
    }

    if os.path.exists('./cache/completions_cache.pkl'):
        cached_data = load_pickle('./cache/completions_cache.pkl')
        cached_data.update(data)
    else:
        cached_data = data

    try:
        with open('./cache/completions_cache.pkl', 'wb') as f:
            pickle.dump(cached_data, f)
    except Exception as e:
        raise e
    
    print(colored(f"Saved completion to cache for question: {question[:100]}", "green"))
    return question_key

def load_answer_from_completion_cache(question, verbose=False):
    """
    Load the completion from the cache.

    Args:
        question (str): The question text.
        verbose (bool, optional): Whether to print verbose output. Defaults to False.

    Returns:
        tuple: The completion answer and the unique identifier for the question.
    """
    if os.path.exists('./cache/completions_cache.pkl'):
        try:
            with open('./cache/completions_cache.pkl', 'rb') as f:
                cached_data = pickle.load(f)
        except Exception as e:
            create_cache_folder_if_not_exists()
            print(colored(f"Error loading completions cache: {e}", "yellow"))
            return None, None

        question_key = create_unique_identifier(question)
        answer = cached_data.get(question_key, None)
        if answer is not None and verbose:
            print(colored(f"Loaded completion from cache for question: {question[:100]}", "green"))
        return answer, question_key
    else:
        if verbose:
            print(colored("Cache file not found", "yellow"))
        return None, None

def delete_cache_entry(question_key_list, verbose=True):
    """
    Delete a cache entry.

    Args:
        question_key_list (str or list): The unique identifier(s) for the question(s) to be deleted.
        verbose (bool, optional): Whether to print verbose output. Defaults to True.
    """
    if os.path.exists('./cache/completions_cache.pkl'):
        try:
            with open('./cache/completions_cache.pkl', 'rb') as f:
                cached_data = pickle.load(f)
        except Exception as e:
            create_cache_folder_if_not_exists()
            print(colored(f"Error loading completions cache: {e}", "yellow"))
            return None
        
        if not isinstance(question_key_list, list):
            question_key_list = [question_key_list]

        for question_key in question_key_list:
            if question_key in cached_data:
                if verbose:
                    print(colored(f"Deleting cache entry for question: {question_key}", "green"))
                try:
                    del cached_data[question_key]
                    with open('./cache/completions_cache.pkl', 'wb') as f:
                        pickle.dump(cached_data, f)
                except Exception as e:
                    print(colored(f"Error deleting cache entry: {e}", "yellow"))
            else:
                print(colored(f"Cache entry not found for question: {question_key}", "yellow"))
    else:
        if verbose:
            print(colored("Cache file not found", "yellow"))

