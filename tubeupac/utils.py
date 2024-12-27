import os
import re
from collections import defaultdict


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