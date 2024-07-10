import os
import re

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
