#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# tubeup.py - Download a video using youtube-dl and upload to the Internet Archive with metadata

# Copyright (C) 2018 Bibliotheca Anonoma
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""tubeupac - Download a video with Youtube-dlc, then upload to Internet Archive, passing all metadata.

Usage:
  tubeupac <url>... [--username <user>] [--password <pass>]
                  [--metadata=<key:value>...]
                  [--cookies=<filename>]
                  [--proxy <proxy>]
                  [--quiet] [--debug]
                  [--use-download-archive]
                  [--output <output>]
                  [--ignore-existing-item]
                  [--skip-download]
                  [--recode-video <rformat>]
                  [--new-item-id <item_id>]
                  [--ydl-option-format <format>]
                  [--ydl-option-subtitleslangs <subtitleslangs>]
                  [--ia-user <ia_user>]
                  [--ia-s3-access <ia_s3_access>]
                  [--ia-s3-secret <ia_s3_secret>]
  tubeupac -h | --help
  tubeupac --version

Arguments:
  <url>                         Youtube-dlc compatible URL to download.
                                Check Youtube-dlc documentation for a list
                                of compatible websites.
  --metadata=<key:value>        Custom metadata to add to the archive.org
                                item.

Options:
  -h --help                    Show this screen.
  -p --proxy <proxy>            Use a proxy while uploading.
  -u --username <user>         Provide a username, for sites like Nico Nico Douga.
  -p --password <pass>         Provide a password, for sites like Nico Nico Douga.
  -a --use-download-archive    Record the video url to the download archive.
                               This will download only videos not listed in
                               the archive file. Record the IDs of all
                               downloaded videos in it.
  -q --quiet                   Just print errors.
  -d --debug                   Print all logs to stdout.
  -o --output <output>         Youtube-dlc output template.
  -i --ignore-existing-item    Don't check if an item already exists on archive.org.
  -s --skip-download           Don't download video but download image and json files.
  --recode-video <rformat>     Re-encode/re-mux the video into another format/container as needed.
                               Same syntax and formats as --remux-video (ex: "mp4").
  --new-item-id <item_id>      New id for archive.org item (ex: "youtube-12345678912").
  --ydl-option-format <format> yt-dlp option format (ex: "bestvideo[height<=1280]+bestaudio").
  --ydl-option-subtitleslangs  <subtitleslangs> yt-dlp option subtitleslangs (ex: "all,-live_chat").
  --ia-user <ia_user>     system user for ia config file loading
  --ia-s3-access <ia_s3_access> s3 access key
  --ia-s3-secret <ia_s3_secret> s3 secret key
"""

import logging
import sys
import traceback

import docopt

from tubeupac.utils import key_value_to_dict
from tubeupac import __version__
from tubeupac.TubeUp import TubeUp


def main(args):
    # Parse arguments from file docstring
    args = docopt.docopt(__doc__, version=__version__)

    URLs = args["<url>"]
    cookie_file = args["--cookies"]
    proxy_url = args["--proxy"]
    username = args["--username"]
    password = args["--password"]
    quiet_mode = args["--quiet"]
    debug_mode = args["--debug"]
    use_download_archive = args["--use-download-archive"]
    ignore_existing_item = args["--ignore-existing-item"]
    skip_download = args["--skip-download"]
    recode_video = args["--recode-video"]
    new_item_id = args["--new-item-id"]
    ydl_option_format = args["--ydl-option-format"]
    ydl_option_subtitleslangs = args["--ydl-option-subtitleslangs"]
    ia_user = args["--ia-user"]
    ia_s3_access = args["--ia-s3-access"]
    ia_s3_secret = args["--ia-s3-secret"]

    if debug_mode:
        # Display log messages.
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "\033[92m[DEBUG]\033[0m %(asctime)s - %(name)s - %(levelname)s - "
            "%(message)s"
        )
        ch.setFormatter(formatter)
        root.addHandler(ch)

    metadata = key_value_to_dict(args['--metadata'])


    tu = TubeUp(verbose=not quiet_mode, output_template=args["--output"], ia_user=ia_user, ia_s3_access=ia_s3_access, ia_s3_secret=ia_s3_secret)

    try:
        for identifier, meta in tu.archive_urls(
            URLs,
            metadata,
            cookie_file,
            proxy_url,
            username,
            password,
            use_download_archive,
            ignore_existing_item,
            skip_download,
            recode_video,
            new_item_id,
            ydl_option_format,
            ydl_option_subtitleslangs,
        ):
            print("\n:: Upload Finished. Item information:")
            print(f'Title: {meta["title"]}')
            print("Item URL: https://archive.org/details/%s\n" % identifier)
    except Exception:
        print(
            "\n\033[91m"  # Start red color text
            "An exception just occured, if you found this "
            "exception isn't related with any of your connection problem, "
            "please report this issue to "
            "https://github.com/altcensored/tubeupac/issues"
        )
        traceback.print_exc()
        print("\033[0m")  # End the red color text
        sys.exit(1)


def run():
    """Calls :func:`main` passing the CLI arguments extracted from :obj:`sys.argv`

    This function can be used as entry point to create console scripts with setuptools.
    """
    main(sys.argv[1:])


if __name__ == "__main__":
    run()
