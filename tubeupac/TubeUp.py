import glob
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from logging import getLogger
from ssl import SSLEOFError
from urllib.parse import urlparse

import internetarchive
from internetarchive.config import parse_config_file
import urllib3.exceptions

from yt_dlp import YoutubeDL
from tubeupac import __version__
from .utils import EMPTY_ANNOTATION_FILE, check_is_file_empty, get_itemname, retry, retry_wrap

DOWNLOAD_DIR_NAME = "downloads"


class TubeUp(object):

    def __init__(
        self,
        verbose=False,
        dir_path="~/.tubeup",
        ia_config_path=None,
        ia_user=None,
        ia_s3_access=None,
        ia_s3_secret=None,
        output_template=None,
    ):
        """
        `tubeupac` is a tool to archive YouTube by downloading the videos and
        uploading it back to the archive.org.

        :param verbose:         A boolean, True means all loggings will be
                                printed out to stdout.
        :param dir_path:        A path to directory that will be used for
                                saving the downloaded resources. Default to
                               '~/.tubeup'.
        :param ia_config_path:  Path to an internetarchive config file, will
                                be used in uploading the file.
        :param output_template: A template string that will be used to
                                generate the output filenames.
        """
        self.dir_path = dir_path
        self.verbose = verbose
        if ia_user:
            ia_config_path = os.path.join(os.path.expanduser('~'+ia_user),'.config','internetarchive','ia.ini')
        self.ia_config_path = ia_config_path
        if ia_s3_access:
            self.ia_s3_access = ia_s3_access
        if ia_s3_secret:
            self.ia_s3_secret = ia_s3_secret
        self.logger = getLogger(__name__)
        if output_template is None:
            self.output_template = "%(id)s.%(ext)s"
        else:
            self.output_template = output_template

        # Just print errors in quiet mode
        if not self.verbose:
            self.logger.setLevel(logging.ERROR)

    @property
    def dir_path(self):
        return self._dir_path

    @dir_path.setter
    def dir_path(self, dir_path):
        """
        Set a directory to be the saving directory for resources that have
        been downloaded.

        :param dir_path:  Path to a directory that will be used to save the
                          videos, if it not created yet, the directory
                          will be created.
        """
        extended_usr_dir_path = os.path.expanduser(dir_path)

        # Create the directories.
        os.makedirs(
            os.path.join(extended_usr_dir_path, DOWNLOAD_DIR_NAME), exist_ok=True
        )

        self._dir_path = {
            "root": extended_usr_dir_path,
            "downloads": os.path.join(extended_usr_dir_path, DOWNLOAD_DIR_NAME),
        }

    def get_resource_basenames(
        self,
        urls,
        cookie_file=None,
        proxy_url=None,
        ydl_username=None,
        ydl_password=None,
        use_download_archive=False,
        ignore_existing_item=False,
        skip_download=False,
        recode_video=None,
        new_item_id=None,
        ydl_option_format=None,
        ydl_option_subtitleslangs=None,
    ):
        """
        Get resource basenames from an url.

        :param urls:                  A list of urls that will be downloaded with
                                      youtubedl.
        :param cookie_file:           A cookie file for YoutubeDL.
        :param proxy_url:             A proxy url for YoutubeDL.
        :param ydl_username:          Username that will be used to download the
                                      resources with youtube_dl.
        :param ydl_password:          Password of the related username, will be used
                                      to download the resources with youtube_dl.
        :param use_download_archive:  Record the video url to the download archive.
                                      This will download only videos not listed in
                                      the archive file. Record the IDs of all
                                      downloaded videos in it.
        :param ignore_existing_item:  Ignores the check for existing items on archive.org.
        :param skip_download:         yt-dlp option to skip download of video. Useful for subtitles only.
        :param recode_video <rformat> Re-encode/re-mux the video into another format/container as needed.
                                      Same syntax and formats as --remux-video (ex: "mp4").
        :param new_item_id:           New id for archive.org item.
        :param ydl_option_format:     yt-dlp format option for YoutubeDL.
        :param ydl_option_subtitleslangs:  yt-dlp subtitleslangs option for YoutubeDL.
        :return:                      Set of videos basename that has been downloaded.
        """
        downloaded_files_basename = set()

        def check_if_ia_item_exists(infodict):
            itemname = get_itemname(infodict, new_item_id)
            item = retry(internetarchive.get_item, func_param=itemname , retries=5, delay=2, exceptions=(Exception,))
            if item.exists and self.verbose:
                print("\n:: Item already exists. Not downloading.")
                print("Title: %s" % infodict["title"])
                print("Extractor: %s" % infodict["extractor"])
                print("Identifier: %s" % itemname)
                print("Video URL: %s" % infodict["webpage_url"])
                print("Item URL: https://archive.org/details/%s\n" % itemname)
                return True
            return False

        def ydl_progress_each(entry):
            if not entry:
                self.logger.warning('Video "%s" is not available. Skipping.' % url)
                return
            if ydl.in_download_archive(entry):
                return
            if not check_if_ia_item_exists(entry):
                ydl.extract_info(entry["webpage_url"])
                downloaded_files_basename.update(
                    self.create_basenames_from_ydl_info_dict(ydl, entry)
                )
            else:
                ydl.record_download_archive(entry)

        def ydl_progress_hook(d):
            if d["status"] == "downloading" and self.verbose:
                if d.get("_total_bytes_str") is not None:
                    msg_template = (
                        "%(_percent_str)s of %(_total_bytes_str)s "
                        "at %(_speed_str)s ETA %(_eta_str)s"
                    )
                elif d.get("_total_bytes_estimate_str") is not None:
                    msg_template = (
                        "%(_percent_str)s of "
                        "~%(_total_bytes_estimate_str)s at "
                        "%(_speed_str)s ETA %(_eta_str)s"
                    )
                elif d.get("_downloaded_bytes_str") is not None:
                    if d.get("_elapsed_str"):
                        msg_template = (
                            "%(_downloaded_bytes_str)s at "
                            "%(_speed_str)s (%(_elapsed_str)s)"
                        )
                    else:
                        msg_template = "%(_downloaded_bytes_str)s " "at %(_speed_str)s"
                else:
                    msg_template = (
                        "%(_percent_str)s % at " "%(_speed_str)s ETA %(_eta_str)s"
                    )

                process_msg = "\r[download] " + (msg_template % d) + "\033[K"
                sys.stdout.write(process_msg)
                sys.stdout.flush()

            if d["status"] == "finished":
                msg = "\nDownloaded %s" % d["filename"]

                self.logger.debug(d)
                self.logger.info(msg)
                if self.verbose:
                    print(msg)

            if d["status"] == "error":
                # TODO: Complete the error message
                msg = "Error when downloading the video"

                self.logger.error(msg)
                if self.verbose:
                    print(msg)

        ydl_opts = self.generate_ydl_options(
            ydl_progress_hook,
            cookie_file,
            proxy_url,
            ydl_username,
            ydl_password,
            use_download_archive,
            skip_download,
            recode_video,
            ydl_option_format,
            ydl_option_subtitleslangs,
        )

        with YoutubeDL(ydl_opts) as ydl:
            for url in urls:
                if not ignore_existing_item:
                    # Get the info dict of the url
                    info_dict = ydl.extract_info(url, download=False)

                    if info_dict.get("_type", "video") == "playlist":
                        for entry in info_dict["entries"]:
                            ydl_progress_each(entry)
                    else:
                        ydl_progress_each(info_dict)
                else:
                    info_dict = ydl.extract_info(url)
                    downloaded_files_basename.update(
                        self.create_basenames_from_ydl_info_dict(ydl, info_dict)
                    )

        self.logger.debug(
            "Basenames obtained from url (%s): %s" % (url, downloaded_files_basename)
        )

        return downloaded_files_basename

    def create_basenames_from_ydl_info_dict(self, ydl, info_dict):
        """
        Create basenames from YoutubeDL info_dict.

        :param ydl:        A `youtube_dl.YoutubeDL` instance.
        :param info_dict:  A ydl info_dict that will be used to create
                           the basenames.
        :return:           A set that contains basenames that created from
                           the `info_dict`.
        """
        info_type = info_dict.get("_type", "video")
        self.logger.debug(
            "Creating basenames from ydl info dict with type %s" % info_type
        )

        filenames = set()

        if info_type == "playlist":
            # Iterate and get the filenames through the playlist
            for video in info_dict["entries"]:
                filenames.add(ydl.prepare_filename(video))
        else:
            filenames.add(ydl.prepare_filename(info_dict))

        basenames = set()

        for filename in filenames:
            filename_without_ext = os.path.splitext(filename)[0]
            file_basename = re.sub(r"(\.f\d+)", "", filename_without_ext)
            basenames.add(file_basename)

        return basenames

    def generate_ydl_options(
        self,
        ydl_progress_hook,
        cookie_file=None,
        proxy_url=None,
        ydl_username=None,
        ydl_password=None,
        use_download_archive=False,
        skip_download=False,
        recode_video=None,
        ydl_option_format=None,
        ydl_option_subtitleslangs=None,
    ):
        """
        Generate a dictionary that contains options that will be used
        by yt-dlp.

        :param ydl_progress_hook:     A function that will be called during the
                                      download process by youtube_dl.
        :param cookie_file:           A cookie file for YoutubeDL.
        :param proxy_url:             A proxy url for YoutubeDL.
        :param ydl_username:          Username that will be used to download the
                                      resources with youtube_dl.
        :param ydl_password:          Password of the related username, will be
                                      used to download the resources with
                                      youtube_dl.
        :param use_download_archive:  Record the video url to the download archive.
                                      This will download only videos not listed in
                                      the archive file. Record the IDs of all
                                      downloaded videos in it.
        :param skip_download:         yt-dlp option to skip download of video. Useful for subtitles only.
        :param recode_video <rformat> Re-encode/re-mux the video into another format/container as needed.
                                      Same syntax and formats as --remux-video (ex: "mp4").
        :param ydl_option_format:     youtube_dl option format
        :param ydl_option_subtitleslangs:  subtitleslangs option for YoutubeDL
        :return:                      A dictionary that contains options that will
                                      be used by youtube_dl.
        """
        ydl_opts = {
            "outtmpl": os.path.join(self.dir_path["downloads"], self.output_template),
            "restrictfilenames": True,
            "quiet": not self.verbose,
            "verbose": self.verbose,
            "progress_with_newline": True,
            "forcetitle": True,
            "continuedl": True,
            "retries": 9001,
            "fragment_retries": 9001,
            "forcejson": False,
            "writeinfojson": True,
            "writedescription": True,
            "writethumbnail": True,
            "writeannotations": True,
            "writesubtitles": True,
            "allsubtitles": True,
            "ignoreerrors": False,  # Geo-blocked,
            # copyrighted/private/deleted
            # will be printed to STDOUT and channel
            # ripping will  continue uninterupted,
            # use with verbose off
            "fixup": "detect_or_warn",  # Slightly more verbosity for debugging
            # problems
            "nooverwrites": True,  # Don't touch what's already been
            # downloaded speeds things
            "consoletitle": True,  # Download percentage in console title
            "prefer_ffmpeg": True,  # `ffmpeg` is better than `avconv`,
            # let's prefer it's use
            # Warns on out of date youtube-dl script, helps debugging for
            # youtube-dl devs
            "call_home": False,
            "logger": self.logger,
            "progress_hooks": [ydl_progress_hook],
            "usenetrc": True,
        }

        if cookie_file is not None:
            ydl_opts["cookiefile"] = cookie_file

        if proxy_url is not None:
            ydl_opts["proxy"] = proxy_url

        if ydl_username is not None:
            ydl_opts["username"] = ydl_username

        if ydl_password is not None:
            ydl_opts["password"] = ydl_password

        if use_download_archive:
            ydl_opts["download_archive"] = os.path.join(
                self.dir_path["root"], ".ytdlarchive"
            )

        if ydl_option_format is not None:
            ydl_opts["format"] = ydl_option_format

        if ydl_option_subtitleslangs is not None:
            ydl_opts["subtitleslangs"] = ydl_option_subtitleslangs

        if recode_video is not None:
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegVideoConvertor", "preferedformat": recode_video}
            ]

        if skip_download:
            ydl_opts["skip_download"] = skip_download

        return ydl_opts

    def upload_ia(self, videobasename, custom_meta=None, new_item_id=None, write_metadata=False):
        """
        Upload video to archive.org.

        :param videobasename:  A video base name.
        :param custom_meta:    A custom meta, will be used by internetarchive
                               library when uploading to archive.org.
        :param new_item_id:    New id for archive.org item (ex: "youtube-12345678912").
        :param write_metadata: Write item metadata as CSV to a file.
        :return:               A tuple containing item name and metadata used
                               when uploading to archive.org and whether the item
                               already exists.
        """
        json_metadata_filepath = videobasename + ".info.json"
        with open(json_metadata_filepath, "r", encoding="utf-8") as f:
            vid_meta = json.load(f)

        # Exit if video download did not complete, don't upload .part files to IA
        for ext in [
            "*.part",
            "*.f303.*",
            "*.f302.*",
            "*.ytdl",
            "*.f251.*",
            "*.248.*",
            "*.f247.*",
            "*.temp",
        ]:
            if glob.glob(videobasename + ext):
                msg = "Video download incomplete, please re-run or delete video stubs in downloads folder, exiting..."
                raise Exception(msg)

        itemname = get_itemname(vid_meta, new_item_id)
        metadata = self.create_archive_org_metadata_from_youtubedl_meta(vid_meta)

        # Delete empty description file
        description_file_path = videobasename + ".description"
        if os.path.exists(description_file_path) and (
            ("description" in vid_meta and vid_meta["description"] == "")
            or check_is_file_empty(description_file_path)
        ):
            os.remove(description_file_path)

        # Delete empty annotations.xml file so it isn't uploaded
        annotations_file_path = videobasename + ".annotations.xml"
        if os.path.exists(annotations_file_path) and (
            (
                "annotations" in vid_meta
                and vid_meta["annotations"] in {"", EMPTY_ANNOTATION_FILE}
            )
            or check_is_file_empty(annotations_file_path)
        ):
            os.remove(annotations_file_path)

        # Upload all files with videobase name: e.g. video.mp4,
        # video.info.json, video.srt, etc.
        files_to_upload = glob.glob(videobasename + "*")

        # Upload the item to the Internet Archive
        item = internetarchive.get_item(itemname)

        if custom_meta:
            metadata.update(custom_meta)

        if write_metadata:
            csv_metadata = dict(identifier=itemname, **metadata)
#            csv_metadata_filepath = videobasename + ".csv"
#            with open(csv_metadata_filepath, 'w', encoding='utf-8', newline='') as f:
            with open('%s.csv' % itemname, 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, csv_metadata.keys())
                w.writeheader()
                w.writerow(csv_metadata)

        # Parse internetarchive configuration file.
        parsed_ia_s3_config = parse_config_file(self.ia_config_path)[2]["s3"]
        s3_access_key = parsed_ia_s3_config["access"]
        s3_secret_key = parsed_ia_s3_config["secret"]

        if self.ia_s3_access:
            s3_access_key = self.ia_s3_access
        if self.ia_s3_secret:
            s3_secret_key = self.ia_s3_secret

        if None in {s3_access_key, s3_secret_key}:
            msg = "`internetarchive` configuration file is not configured" " properly."

            self.logger.error(msg)
            if self.verbose:
                print(msg)
            raise Exception(msg)

        @retry_wrap(tries=3, delay=10, backoff=3, exceptions=(urllib3.exceptions.ProtocolError, urllib3.exceptions.TimeoutError, urllib3.exceptions.ConnectionError, urllib3.exceptions.MaxRetryError, urllib3.exceptions.SSLError, urllib3.exceptions.ReadTimeoutError, SSLEOFError))
        def item_upload_wrap():
            item.upload(
                files_to_upload,
                metadata=metadata,
                retries=9001,
                request_kwargs=dict(timeout=(360,360)),
                delete=False,
                verbose=self.verbose,
                access_key=s3_access_key,
                secret_key=s3_secret_key,
            )

        item_upload_wrap()

        for f in files_to_upload:
            os.remove(f)

        return itemname, metadata

    def archive_urls(
        self,
        urls,
        custom_meta=None,
        cookie_file=None,
        proxy=None,
        ydl_username=None,
        ydl_password=None,
        use_download_archive=False,
        ignore_existing_item=False,
        skip_download=False,
        recode_video=None,
        new_item_id=None,
        ydl_option_format=None,
        ydl_option_subtitleslangs=None,
        write_metadata=False,
    ):
        """
        Download and upload videos from youtube_dl supported sites to
        archive.org

        :param urls:                  List of url that will be downloaded and uploaded
                                      to archive.org
        :param custom_meta:           A custom metadata that will be used when
                                      uploading the file with archive.org.
        :param cookie_file:           A cookie file for YoutubeDL.
        :param proxy:                 A proxy url for YoutubeDL.
        :param ydl_username:          Username that will be used to download the
                                      resources with youtube_dl.
        :param ydl_password:          Password of the related username, will be used
                                      to download the resources with youtube_dl.
        :param use_download_archive:  Record the video url to the download archive.
                                      This will download only videos not listed in
                                      the archive file. Record the IDs of all
                                      downloaded videos in it.
        :param ignore_existing_item:  Ignores the check for existing items on archive.org.
        :param skip_download:         yt-dlp option to skip download of video. Useful for subtitles only.
        :param recode_video <rformat> Re-encode/re-mux the video into another format/container as needed.
                                      Same syntax and formats as --remux-video (ex: "mp4").
        :param new_item_id:           New id for archive.org item
        :param ydl_option_format:     YoutubeDL option format.
        :param ydl_option_subtitleslangs:  subtitleslangs option for YoutubeDL
        :return:                      Tuple containing identifier and metadata of the
                                      file that has been uploaded to archive.org.
        :param write_metadata:        Write CSV metadata for each item uploaded
                                      to archive.org.
        """
        downloaded_file_basenames = self.get_resource_basenames(
            urls,
            cookie_file,
            proxy,
            ydl_username,
            ydl_password,
            use_download_archive,
            ignore_existing_item,
            skip_download,
            recode_video,
            new_item_id,
            ydl_option_format,
            ydl_option_subtitleslangs,
        )
        for basename in downloaded_file_basenames:
            identifier, meta = self.upload_ia(basename, custom_meta, new_item_id, write_metadata)
            yield identifier, meta

    @staticmethod
    def determine_collection_type(url):
        """
        Determine collection type for an url.

        :param url:  URL that the collection type will be determined.
        :return:     String, name of a collection.
        """
        if urlparse(url).netloc == "soundcloud.com":
            return "opensource_audio"
        return "opensource_movies"

    @staticmethod
    def determine_licenseurl(vid_meta):
        """
        Determine licenseurl for an url

        :param vid_meta:
        :return:
        """
        licenseurl = ""
        licenses = {
            "Creative Commons Attribution license (reuse allowed)": "https://creativecommons.org/licenses/by/3.0/",
            "Attribution-NonCommercial-ShareAlike": "https://creativecommons.org/licenses/by-nc-sa/2.0/",
            "Attribution-NonCommercial": "https://creativecommons.org/licenses/by-nc/2.0/",
            "Attribution-NonCommercial-NoDerivs": "https://creativecommons.org/licenses/by-nc-nd/2.0/",
            "Attribution": "https://creativecommons.org/licenses/by/2.0/",
            "Attribution-ShareAlike": "https://creativecommons.org/licenses/by-sa/2.0/",
            "Attribution-NoDerivs": "https://creativecommons.org/licenses/by-nd/2.0/",
        }

        if "license" in vid_meta and vid_meta["license"]:
            licenseurl = licenses.get(vid_meta["license"])

        return licenseurl

    @staticmethod
    def create_archive_org_metadata_from_youtubedl_meta(vid_meta):
        """
        Create an archive.org from youtubedl-generated metadata.

        :param vid_meta: A dict containing youtubedl-generated metadata.
        :return:         A dict containing metadata to be used by
                         internetarchive library.
        """
        title = "%s" % (vid_meta["title"])
        videourl = vid_meta["webpage_url"]

        collection = TubeUp.determine_collection_type(videourl)

        # Some video services don't tell you the uploader,
        # use our program's name in that case.
        try:
            if (
                vid_meta["extractor_key"] == "TwitchClips"
                and "creator" in vid_meta
                and vid_meta["creator"]
            ):
                uploader = vid_meta["creator"]
            elif "uploader" in vid_meta and vid_meta["uploader"]:
                uploader = vid_meta["uploader"]
            elif "uploader_url" in vid_meta and vid_meta["uploader_url"]:
                uploader = vid_meta["uploader_url"]
            else:
                uploader = "tubeup.py"
        except TypeError:  # apparently uploader is null as well
            uploader = "tubeup.py"

        try:  # some videos don't give an upload date
            d = datetime.strptime(vid_meta["upload_date"], "%Y%m%d")
            upload_date = d.isoformat().split("T")[0]
            upload_year = upload_date[:4]  # 20150614 -> 2015
        except (KeyError, TypeError):
            # Use current date and time as default values
            upload_date = time.strftime("%Y-%m-%d")
            upload_year = time.strftime("%Y")

        # load up tags into an IA compatible semicolon-separated string
        # example: Youtube;video;
        tags_string = "%s;video;" % vid_meta["extractor_key"]

        if "categories" in vid_meta:
            # add categories as tags as well, if they exist
            try:
                for category in vid_meta["categories"]:
                    tags_string += "%s;" % category
            except Exception:
                print("No categories found.")

        if "tags" in vid_meta:  # some video services don't have tags
            try:
                if "tags" in vid_meta is None:
                    tags_string += "%s;" % vid_meta["id"]
                    tags_string += "%s;" % "video"
                else:
                    for tag in vid_meta["tags"]:
                        tags_string += "%s;" % tag
            except Exception:
                print("Unable to process tags successfully.")

        # IA's subject field has a 255 bytes length limit, so we need to truncate tags_string
        while len(tags_string.encode("utf-8")) > 255:
            tags_list = tags_string.split(";")
            tags_list.pop()
            tags_string = ";".join(tags_list)

        # license
        licenseurl = TubeUp.determine_licenseurl(vid_meta)

        # if there is no description don't upload the empty .description file
        description_text = vid_meta.get("description", "")
        if description_text is None:
            description_text = ""
        # archive.org does not display raw newlines
        description = re.sub("\r?\n", "<br>", description_text)

        metadata = dict(
            mediatype=("audio" if collection == "opensource_audio" else "movies"),
            creator=uploader,
            collection=collection,
            title=title,
            description=description,
            date=upload_date,
            year=upload_year,
            subject=tags_string,
            originalurl=videourl,
            licenseurl=licenseurl,
            # Set 'scanner' metadata pair to allow tracking of TubeUp
            # powered uploads, per request from archive.org
            scanner="TubeUp Video Stream Mirroring Application {}".format(__version__),
        )

        # add channel url if it exists
        if "uploader_url" in vid_meta:
            metadata["channel"] = vid_meta["uploader_url"]
        elif "channel_url" in vid_meta:
            metadata["channel"] = vid_meta["channel_url"]

        return metadata
