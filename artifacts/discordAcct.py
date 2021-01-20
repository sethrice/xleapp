import errno
import gzip
import json
import os
import re
import shutil
import string
from pathlib import Path

from html_report.artifact_report import ArtifactHtmlReport
from packaging import version
from tools.ilapfuncs import (is_platform_windows, logdevinfo, logfunc,
                             timeline, tsv)

import artifacts.artGlobals

from artifacts.Artifact import AbstractArtifact


class DiscordAcct(AbstractArtifact):

    _name = 'Discord Account'
    _search_dirs = ('*/var/mobile/Containers/Data/Application/*/Documents/mmkv/mmkv.default')
    _report_section = 'Discord'

    @staticmethod
    def get(files_found, report_folder, seeker):
        searchlist = []
        for file_found in files_found:
            file_found = str(file_found)
            
            for s in strings(file_found):
                #print(type(s))
                #print(s)
                searchlist.append(str(s),)

            counter = 0
            data_list = []
            for x in searchlist:
                counter += 1
                if 'user_id_cache' in x:
                    #print(x)
                    wf = searchlist[counter].split('"')
                    try:
                        data_list.append(('USER_ID_CACHE', wf[1]))
                    except:
                        pass
                    
                if 'email_cache' in x:
                    #print(x)
                    wfa = searchlist[counter].split('"')
                    try:
                        data_list.append(('EMAIL_CACHE', wfa[1]))
                    except:
                        pass

        if len(data_list) > 0:		
            report = ArtifactHtmlReport('Discord Account')
            report.start_artifact_report(report_folder, 'Discord Account')
            report.add_script()
            data_headers = ('Key', 'Value')   
            report.write_artifact_data_table(data_headers, data_list, file_found)
            report.end_artifact_report()
            
            tsvname = 'Discord Account'
            tsv(report_folder, data_headers, data_list, tsvname)

def strings(filename, min=4):
    with open(filename, errors="ignore") as f:  # Python 3.x
        # with open(filename, "rb") as f:           # Python 2.x
        result = ""
        for c in f.read():
            if c in string.printable:
                result += c
                continue
            if len(result) >= min:
                yield result
            result = ""
        if len(result) >= min:  # catch result at EOF
            yield result