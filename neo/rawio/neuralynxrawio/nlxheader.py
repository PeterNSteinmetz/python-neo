import datetime
from packaging.version import Version
import os
import re
from collections import OrderedDict

from neo.rawio.neuralynxrawio.ncssections import AcqType


class NlxHeader(OrderedDict):
    """
    Representation of basic information in all 16 kbytes Neuralynx file headers,
    including dates opened and closed if given.

    The OrderedDict contains entries for each property given in the header with '-' in front
    of the key value as well as an 'ApplicationName', 'ApplicationVersion', 'recording_opened'
    and 'recording_closed' entries. The 'InputRange', 'channel_ids', 'channel_names' and
    'bit_to_microvolt' properties are set to lists of entries for each channel which may be
    in the file.
    """

    HEADER_SIZE = 2**14  # Neuralynx files have a txt header of 16kB

    # helper function to interpret boolean keys
    def _to_bool(txt):
        if txt == "True":
            return True
        elif txt == "False":
            return False
        else:
            raise Exception("Can not convert %s to bool" % txt)

    # Keys that may be present in header which we parse. First entry of tuple is what is
    # present in header, second entry is key which will be used in dictionary, third entry
    # type the value will be converted to.
    txt_header_keys = [
        ("AcqEntName", "channel_names", None),  # used
        ("FileType", "", None),
        ("FileVersion", "", None),
        ("RecordSize", "", None),
        ("HardwareSubSystemName", "", None),
        ("HardwareSubSystemType", "", None),
        ("SamplingFrequency", "sampling_rate", float),  # used
        ("ADMaxValue", "", None),
        ("ADBitVolts", "bit_to_microVolt", None),  # used
        ("NumADChannels", "", None),
        ("ADChannel", "channel_ids", None),  # used
        ("InputRange", "", None),
        ("InputInverted", "input_inverted", _to_bool),  # used
        ("DSPLowCutFilterEnabled", "", None),
        ("DspLowCutFrequency", "", None),
        ("DspLowCutNumTaps", "", None),
        ("DspLowCutFilterType", "", None),
        ("DSPHighCutFilterEnabled", "", None),
        ("DspHighCutFrequency", "", None),
        ("DspHighCutNumTaps", "", None),
        ("DspHighCutFilterType", "", None),
        ("DspDelayCompensation", "", None),
        ("DspFilterDelay_µs", "", None),
        ("DisabledSubChannels", "", None),
        ("WaveformLength", "", int),
        ("AlignmentPt", "", None),
        ("ThreshVal", "", None),
        ("MinRetriggerSamples", "", None),
        ("SpikeRetriggerTime", "", None),
        ("DualThresholding", "", None),
        (r"Feature \w+ \d+", "", None),
        ("SessionUUID", "", None),
        ("FileUUID", "", None),
        ("CheetahRev", "", None),  # only for older versions of Cheetah
        ("ProbeName", "", None),
        ("OriginalFileName", "", None),
        ("TimeCreated", "", None),
        ("TimeClosed", "", None),
        ("ApplicationName", "", None),  # also include version number when present
        ("AcquisitionSystem", "", None),
        ("ReferenceChannel", "", None),
        ("NLX_Base_Class_Type", "", None),  # in version 4 and earlier versions of Cheetah
    ]

    def __init__(self, filename, props_only=False):
        """
        Factory function to build NlxHeader for a given file.

        :param filename: name of Neuralynx file
        :param props_only: if true, will not try and read time and date or check start
        """
        super(OrderedDict, self).__init__()
        with open(filename, "rb") as f:
            txt_header = f.read(NlxHeader.HEADER_SIZE)
        txt_header = txt_header.strip(b"\x00").decode("latin-1")

        # must start with 8 # characters
        if not props_only and not txt_header.startswith("########"):
            ValueError("Neuralynx files must start with 8 # characters.")

        self.read_properties(filename, txt_header)
        numChidEntries = self.convert_channel_ids_names(filename)
        self.setApplicationAndVersion()
        self.setBitToMicroVolt()
        self.setInputRanges(numChidEntries)
        # :TODO: needs to also handle filename property

        if not props_only:
            self.readTimeDate(txt_header)

    def read_properties(self, filename, txt_header):
        """
        Read properties from header and place in OrderedDictionary which this object is.
        :param filename: name of ncs file, used for extracting channel number
        :param txt_header: header text
        """
        # find keys
        for k1, k2, type_ in NlxHeader.txt_header_keys:
            pattern = r"-(?P<name>" + k1 + r")\s+(?P<value>[\S ]*)"
            matches = re.findall(pattern, txt_header)
            for match in matches:
                if k2 == "":
                    name = match[0]
                else:
                    name = k2
                value = match[1].rstrip(" ")
                if type_ is not None:
                    value = type_(value)
                self[name] = value

    def setInputRanges(self, numChidEntries):
        if "InputRange" in self:
            ir_entries = re.findall(r"\w+", self["InputRange"])
            if len(ir_entries) == 1:
                self["InputRange"] = [int(ir_entries[0])] * numChidEntries
            else:
                self["InputRange"] = [int(e) for e in ir_entries]
            assert len(self["InputRange"]) == numChidEntries, \
                "Number of channel ids does not match input range values."

    def setBitToMicroVolt(self):
        # convert bit_to_microvolt
        if "bit_to_microVolt" in self:
            btm_entries = re.findall(r"\S+", self["bit_to_microVolt"])
            if len(btm_entries) == 1:
                btm_entries = btm_entries * len(self["channel_ids"])
            self["bit_to_microVolt"] = [float(e) * 1e6 for e in btm_entries]
            assert len(self["bit_to_microVolt"]) == len( self["channel_ids"]), \
                "Number of channel ids does not match bit_to_microVolt conversion factors."

    def setApplicationAndVersion(self):
        """
        Set "ApplicationName" property and app_version attribute based on existing properties
        """
        # older Cheetah versions with CheetahRev property
        if "CheetahRev" in self:
            assert "ApplicationName" not in self
            self["ApplicationName"] = "Cheetah"
            app_version = self["CheetahRev"]
        # new file version 3.4 does not contain CheetahRev property, but ApplicationName instead
        elif "ApplicationName" in self:
            pattern = r'(\S*) "([\S ]*)"'
            match = re.findall(pattern, self["ApplicationName"])
            assert len(match) == 1, "impossible to find application name and version"
            self["ApplicationName"], app_version = match[0]
        # BML Ncs file contain neither property, but 'NLX_Base_Class_Type'
        elif "NLX_Base_Class_Type" in self:
            self["ApplicationName"] = "BML"
            app_version = "2.0"
        # Neuraview Ncs file contained neither property nor NLX_Base_Class_Type information
        else:
            self["ApplicationName"] = "Neuraview"
            app_version = "2"

        if " Development" in app_version:
            app_version = app_version.replace(" Development", ".dev0")

        self["ApplicationVersion"] = Version(app_version)

    def convert_channel_ids_names(self, filename):
        """
        Convert channel ids and channel name properties, if present.

        :return number of channel id entries
        """
        # if channel_ids or names not in self then the filename is used for channel name
        name = os.path.splitext(os.path.basename(filename))[0]

        # convert channel ids
        if "channel_ids" in self:
            chid_entries = re.findall(r"\S+", self["channel_ids"])
            self["channel_ids"] = [int(c) for c in chid_entries]
        else:
            self["channel_ids"] = ["unknown"]
            chid_entries = []

        # convert channel names
        if "channel_names" in self:
            name_entries = re.findall(r"\S+", self["channel_names"])
            if len(name_entries) == 1:
                self["channel_names"] = name_entries * len(self["channel_ids"])
            assert len(self["channel_names"]) == len(
                self["channel_ids"]
            ), "Number of channel ids does not match channel names."
        else:
            self["channel_names"] = ["unknown"] * len(self["channel_ids"])

        return len(chid_entries)

    # Filename and datetime may appear in header lines starting with # at
    # beginning of header or in later versions as a property. The exact format
    # used depends on the application name and its version as well as the
    # -FileVersion property.
    #
    # There are 4 styles understood by this code and the patterns used for parsing
    # the items within each are stored in a dictionary. Each dictionary is then
    # stored in main dictionary keyed by an abbreviation for the style.
    header_pattern_dicts = {
        # BML - example
        # ######## Neuralynx Data File Header
        # ## File Name: null
        # ## Time Opened: (m/d/y): 12/11/15  At Time: 11:37:39.000
        "bml": dict(
            datetime1_regex=r"## Time Opened: \(m/d/y\): (?P<date>\S+)" r"  At Time: (?P<time>\S+)",
            filename_regex=r"## File Name: (?P<filename>\S+)",
            datetimeformat="%m/%d/%y %H:%M:%S.%f",
        ),
        # Cheetah after version 1 and before version 5 - example
        # ######## Neuralynx Data File Header
        # ## File Name F:\2000-01-01_18-28-39\RMH3.ncs
        # ## Time Opened (m/d/y): 1/1/2000  (h:m:s.ms) 18:28:39.821
        # ## Time Closed (m/d/y): 1/1/2000  (h:m:s.ms) 9:58:41.322

        # Cheetah version 4.0.2 - example
        # ######## Neuralynx Data File Header
        # ## File Name: D:\Cheetah_Data\2003-10-4_10-2-58\CSC14.Ncs
        # ## Time Opened: (m/d/y): 10/4/2003  At Time: 10:3:0.578

        # Cheetah version 5.4.0 - example
        # ######## Neuralynx Data File Header
        # ## File Name C:\CheetahData\2000-01-01_00-00-00\CSC5.ncs
        # ## Time Opened (m/d/y): 1/01/2001  At Time: 0:00:00.000
        # ## Time Closed (m/d/y): 1/01/2001  At Time: 00:00:00.000
        "v5.4.0": dict(
            datetime1_regex=r"## Time Opened \(m/d/y\): (?P<date>\S+)" r"  At Time: (?P<time>\S+)",
            datetime2_regex=r"## Time Closed \(m/d/y\): (?P<date>\S+)" r"  At Time: (?P<time>\S+)",
            filename_regex=r"## File Name: (?P<filename>\S+)",
            datetimeformat="%m/%d/%Y %H:%M:%S.%f",
        ),
        # Cheetah version 5.5.1 - example
        # ######## Neuralynx Data File Header
        # ## File Name C:\CheetahData\2013-11-29_17-05-05\Tet3a.ncs
        # ## Time Opened (m/d/y): 11/29/2013  (h:m:s.ms) 17:5:16.793
        # ## Time Closed (m/d/y): 11/29/2013  (h:m:s.ms) 18:3:13.603

        # Cheetah version 5.6.0 - example
        # ## File Name: F:\processing\sum-big-board\252-1375\recording-20180107\2018-01-07_15-14-54\04. tmaze1-no-light-start To tmaze1-light-stop\VT1_fixed.nvt
        # ## Time Opened: (m/d/y): 2/5/2018 At Time: 18:5:12.654

        # Cheetah version 5.6.3 - example
        # ######## Neuralynx Data File Header
        # ## File Name C:\CheetahData\2016-11-28_21-50-00\CSC1.ncs
        # ## Time Opened (m/d/y): 11/28/2016  (h:m:s.ms) 21:50:33.322
        # ## Time Closed (m/d/y): 11/28/2016  (h:m:s.ms) 22:44:41.145

        # Cheetah version 5 before and including v 5.6.4 as well as version 1
        "bv5.6.4": dict(
            datetime1_regex=r"## Time Opened \(m/d/y\): (?P<date>\S+)" r"  \(h:m:s\.ms\) (?P<time>\S+)",
            datetime2_regex=r"## Time Closed \(m/d/y\): (?P<date>\S+)" r"  \(h:m:s\.ms\) (?P<time>\S+)",
            filename_regex=r"## File Name (?P<filename>\S+)",
            datetimeformat="%m/%d/%Y %H:%M:%S.%f",
        ),

        # Cheetah version 5.7.4 - example
        # ######## Neuralynx Data File Header
        # and then properties
        # -OriginalFileName "C:\CheetahData\2017-02-16_17-55-55\CSC1.ncs"
        # -TimeCreated 2017/02/16 17:56:04
        # -TimeClosed 2017/02/16 18:01:18

        # Cheetah version 6.3.2 - example
        # ######## Neuralynx Data File Header
        # and then properties
        # -OriginalFileName "G:\CheetahDataD\2019-07-12_13-21-32\CSC1.ncs"
        # -TimeCreated 2019/07/12 13:21:32
        # -TimeClosed 2019/07/12 15:07:55

        # Cheetah version 6.4.1dev - example
        # ######## Neuralynx Data File Header
        # and then properties
        # -OriginalFileName "D:\CheetahData\2021-02-26_15-46-33\CSC1.ncs"
        # -TimeCreated 2021/02/26 15:46:52
        # -TimeClosed 2021/10/12 09:07:58

        # neuraview version 2 - example
        # ######## Neuralynx Data File Header
        # ## File Name: L:\McHugh Lab\Recording\2015-06-24_18-05-11\NeuraviewEventMarkers-20151214_SleepScore.nev
        # ## Date Opened: (mm/dd/yyy): 12/14/2015 At Time: 15:58:32
        # ## Date Closed: (mm/dd/yyy): 12/14/2015 At Time: 15:58:32
        "neuraview2": dict(
            datetime1_regex=r"## Date Opened: \(mm/dd/yyy\): (?P<date>\S+)" r" At Time: (?P<time>\S+)",
            datetime2_regex=r"## Date Closed: \(mm/dd/yyy\): (?P<date>\S+)" r" At Time: (?P<time>\S+)",
            filename_regex=r"## File Name: (?P<filename>\S+)",
            datetimeformat="%m/%d/%Y %H:%M:%S",
        ),
        # pegasus version 2.1.1 and Cheetah beyond version 5.6.4 - example
        # ######## Neuralynx Data File Header
        # and then properties
        # -OriginalFileName D:\Pegasus Data\Dr_NM\1902\2019-06-28_17-36-50\Events_0008.nev
        # -TimeCreated 2019/06/28 17:36:50
        # -TimeClosed 2019/06/28 17:45:48
        "inProps": dict(
            datetime1_regex=r"-TimeCreated (?P<date>\S+) (?P<time>\S+)",
            datetime2_regex=r"-TimeClosed (?P<date>\S+) (?P<time>\S+)",
            filename_regex=r'-OriginalFileName "?(?P<filename>\S+)"?',
            datetimeformat=r"%Y/%m/%d %H:%M:%S",
            datetime2format=r"%Y/%m/%d %H:%M:%S.%f",
        ),
        # general version for in date and time in ## header lines
        "inHeader": dict(
            datetime1_regex=r"## Time Opened: \(m/d/y\): (?P<date>\S+)" r"  At Time: (?P<time>\S+)",
            datetimeformat="%m/%d/%y %H:%M:%S.%f",
        )
    }

    def readTimeDate(self, txt_header):
        """
        Read time and date from text of header appropriate for app name and version

        :TODO: this works for current examples but is not likely actually related
        to app version in this manner.
        """
        an = self["ApplicationName"]
        if an == "Cheetah":
            av = self["ApplicationVersion"]
            if av <= Version("2"):  # version 1 uses same as older versions
                hpd = NlxHeader.header_pattern_dicts["bv5.6.4"]
            elif av < Version("5"):
                hpd = NlxHeader.header_pattern_dicts["inHeader"]
            elif av <= Version("5.4.0"):
                hpd = NlxHeader.header_pattern_dicts["v5.4.0"]
            elif av == Version("5.6.0"):
                hpd = NlxHeader.header_pattern_dicts["inHeader"]
            elif av <= Version("5.6.4"):
                hpd = NlxHeader.header_pattern_dicts["bv5.6.4"]
            else:
                hpd = NlxHeader.header_pattern_dicts["inProps"]
        elif an == "BML":
            hpd = NlxHeader.header_pattern_dicts["inHeader"]
            av = Version("2")
        elif an == "Neuraview":
            hpd = NlxHeader.header_pattern_dicts["neuraview2"]
            av = Version("2")
        elif an == "Pegasus":
            hpd = NlxHeader.header_pattern_dicts["inProps"]
            av = Version("2")
        else:
            an = "Unknown"
            av = "NA"
            hpd = NlxHeader.header_pattern_dicts["inProps"]

        # opening time
        sr = re.search(hpd["datetime1_regex"], txt_header)
        if not sr:
            raise IOError(
                f"No matching header open date/time for application {an} " + f"version {av}. Please contact developers."
            )
        else:
            dt1 = sr.groupdict()
            try:  # allow two possible formats for date and time
                self["recording_opened"] = datetime.datetime.strptime(
                    dt1["date"] + " " + dt1["time"], hpd["datetimeformat"]
                )
            except:
                try:
                    self["recording_opened"] = datetime.datetime.strptime(
                        dt1["date"] + " " + dt1["time"], hpd["datetime2format"]
                    )
                except:
                    self["recording_opened"] = None

        # close time, if available
        if "datetime2_regex" in hpd:
            sr = re.search(hpd["datetime2_regex"], txt_header)
            if not sr:
                raise IOError(
                    f"No matching header close date/time for application {an} "
                    + f"version {av}. Please contact developers."
                )
            else:
                try:
                    dt2 = sr.groupdict()
                    self["recording_closed"] = datetime.datetime.strptime(
                        dt2["date"] + " " + dt2["time"], hpd["datetimeformat"]
                    )
                except:
                    self["recording_closed"] = None

    def type_of_recording(self):
        """
        Determines type of recording in Ncs file with this header.

        RETURN: NcsSections.AcqType
        """

        if "NLX_Base_Class_Type" in self:

            # older style standard neuralynx acquisition with rounded sampling frequency
            if self["NLX_Base_Class_Type"] == "CscAcqEnt":
                return AcqType.PRE4

            # BML style with fractional frequency and microsPerSamp
            elif self["NLX_Base_Class_Type"] == "BmlAcq":
                return AcqType.BML

            else:
                return AcqType.UNKNOWN

        elif "HardwareSubSystemType" in self:

            # DigitalLynx
            if self["HardwareSubSystemType"] == "DigitalLynx":
                return AcqType.DIGITALLYNX

            # DigitalLynxSX
            elif self["HardwareSubSystemType"] == "DigitalLynxSX":
                return AcqType.DIGITALLYNXSX

            # Cheetah64
            elif self["HardwareSubSystemType"] == "Cheetah64":
                return AcqType.CHEETAH64

            # RawDataFile
            elif self["HardwareSubSystemType"] == "RawDataFile":
                return AcqType.RAWDATAFILE

            else:
                return AcqType.UNKNOWN

        elif "FileType" in self:

            if "FileVersion" in self and self["FileVersion"] in ["3.2", "3.3", "3.4"]:
                return AcqType[self["AcquisitionSystem"].split()[1].upper()]

            else:
                return AcqType.CHEETAH560  # only known case of FileType without FileVersion

        else:
            return AcqType.UNKNOWN
