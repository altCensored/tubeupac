import os
import re
import time
from collections import defaultdict
from functools import wraps

EMPTY_ANNOTATION_FILE = (
    '<?xml version="1.0" encoding="UTF-8" ?>'
    "<document><annotations></annotations></document>"
)


def sanitize_identifier(identifier, replacement="-"):
    return re.sub(r"[^\w-]", replacement, identifier)


def get_itemname(infodict, new_item_id=None):
    # Remove illegal characters in identifier
    return sanitize_identifier(
        "%s-%s"
        % (
            update_extractor(infodict.get("extractor"), new_item_id),
            update_id(infodict.get("display_id", infodict.get("id")), new_item_id),
        )
    )


def check_is_file_empty(filepath):
    """
    Check whether file is empty or not.

    :param filepath:  Path of a file that will be checked.
    :return:          True if the file empty.
    """
    if os.path.exists(filepath):
        return os.stat(filepath).st_size == 0
    else:
        raise FileNotFoundError("Path '%s' doesn't exist" % filepath)


def update_extractor(extractor, new_item_id):
    # change extractor to 'youtube' for standard IA naming
    # if yt-dlp youtube extractor used OR --new-item-id option used
    # example: 'youtube+oath2' OR 'bitchute' becomes 'youtube'
    if extractor.startswith("youtube+") or new_item_id is not None:
        return "youtube"
    else:
        return extractor


def update_id(extractor, new_item_id):
    # change id to new_item_id if not None
    if new_item_id is not None:
        return new_item_id
    else:
        return extractor


def key_value_to_dict(lst):
    """
    Convert many key:value pair strings into a python dictionary
    """
    if not isinstance(lst, list):
        lst = [lst]

    result = defaultdict(list)
    for item in lst:
        key, value = item.split(":", 1)
        assert value, f"Expected a value! for {key}"
        if result[key] and value not in result[key]:
            result[key].append(value)
        else:
            result[key] = [value]

    # Convert single-item lists back to strings for non-list values
    return {k: v if len(v) > 1 else v[0] for k, v in result.items()}


def retry(func, func_param, retries=3, delay=1, exceptions=(Exception,)):
    """
    Retries a function with a specified number of attempts and delay between retries.

    Args:
        func (callable): The function to retry.
        func_param: A parameter for the function to retry.
        retries (int, optional): Maximum number of retries. Defaults to 3.
        delay (int, optional): Delay in seconds between retries. Defaults to 1.
        exceptions (tuple, optional): A tuple of exception types to catch and retry on. Defaults to (Exception,).

    Returns:
        Any: The return value of the function if successful.
        None: If the maximum number of retries is reached and the function still fails.
    """
    for attempt in range(retries):
        try:
            return func(func_param)
        except exceptions as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    print(f"Function failed after {retries} attempts.")
    return None


def retry_wrap(tries, delay=1, backoff=2, exceptions=(Exception,)):
    """Retries a function or method until it returns True or exceeds the maximum tries.

    Args:
        tries (int): Maximum number of attempts.
        delay (int): Initial delay between attempts in seconds.
        backoff (int): Multiplier for the delay between attempts.
        exceptions (tuple, optional): A tuple of exception types to catch and retry on. Defaults to (Exception,).
    """

    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    print(f"Retrying in {mdelay} seconds, {mtries - 1} tries remaining. Error: {e}")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)  # Last attempt

        return f_retry

    return deco_retry