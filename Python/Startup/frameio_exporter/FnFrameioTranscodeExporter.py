# Copyright (c) 2011 The Foundry Visionmongers Ltd.  All Rights Reserved.

import os.path
import tempfile
import re
import sys
import math
import traceback
import copy

import hiero.core
import hiero.core.log as log
import hiero.core.nuke as nuke

from hiero.exporters import FnTranscodeExporter, FnTranscodeExporterUI

from hiero.exporters.FnTranscodeExporter import TranscodeExporter, TranscodePreset
from hiero.exporters.FnExternalRender import NukeRenderTask

from FnFrameioUI import gIconPath

class FrameioTranscodeExporter(FnTranscodeExporter.TranscodeExporter):
  def __init__(self, initDict):
    """Sub-class Transcode Exporter to handle uploading of files to Frame.io services"""
    FnTranscodeExporter.TranscodeExporter.__init__( self, initDict )

    self.frameioDelegate = hiero.core.frameioDelegate
    self.originalItem = None
    self.originalItemTag = None
    self.frameIOFileReference = ""
    self.transcodeFinished = False # Set to True if a Transcode Task completes
    self.uploadFinished = False # Set to True when the UploadTask completes
    self.uploadOnly = False # True if the item to be uploaded does not require transccoding
    self.fileToUpload = ""
    self.frameioProject =  "NukeStudio" # This should get set properly
    self._logFile = None

  def startTask(self):   
    # For Clips which are already QuickTime movies, we just upload them without Transcoding

    

    if not self.frameioDelegate.frameioSession.sessionAuthenticated:
      self.setError("Please Log in to Frame.io before Exporting")
      self._progress = 1.0
      self._finished = True
      return

    print "Starting Task..."

    self.frameioProject = self._preset.properties()["frameio_project"]

    # This only works if the export item is a Sequence
    if isinstance(self._item, hiero.core.Clip):        
      print "Got a Clip, just upload it, with methods :%s" % (str(dir(self._item)))

      originalFileName = self._item.mediaSource().fileinfos()[0].filename()
      #filePath = self.resolvedExportPath()
      ext = os.path.splitext(originalFileName)[1].lower()
      if hiero.core.isQuickTimeFileExtension(ext):
        
        self.uploadOnly = True
        self._progress = 0.5
        print "Got a QuickTime Clip, upload it to Frame.io, filePath: %s, frameioProject: %s" % (self.fileToUpload, self.frameioProject)
        self.fileToUpload = self.frameioDelegate.uploadFile(originalFileName, self.frameioProject)
        self._progress = 1.0
        self._finished = True
        return
        
      else:
        FnTranscodeExporter.TranscodeExporter.startTask(self)
    else:
      print "Got a Sequence or Shot, need to transcode first"
      FnTranscodeExporter.TranscodeExporter.startTask(self)

  def updateItem (self, originalItem, localtime):
    """updateItem - This is called by the processor prior to taskStart, crucially on the main thread.\n
      This gives the task an opportunity to modify the original item on the main thread, rather than the clone."""

    print "updateItem called"

    timestamp = self.timeStampString(localtime)
    tagName = str("Transcode {0} {1}").format(self._preset.properties()["file_type"], timestamp)
    self.originalItemTag = hiero.core.Tag(tagName, os.path.join(gIconPath, "frameio.png"))

    self.originalItemTag.metadata().setValue("tag.pathtemplate", self._exportPath)
    self.originalItemTag.metadata().setValue("tag.description", "Frame.io Upload " + self._preset.properties()["file_type"])

    self.originalItemTag.metadata().setValue("tag.path", self.resolvedExportPath())
    self.originalItemTag.metadata().setValue("tag.localtime", str(localtime))

    # No point in adding script path if we're not planning on keeping the script
    if self._preset.properties()["keepNukeScript"]:
      self.originalItemTag.metadata().setValue("tag.script", self._scriptfile)

    start, end = self.outputRange()
    self.originalItemTag.metadata().setValue("tag.startframe", str(start))
    self.originalItemTag.metadata().setValue("tag.duration", str(end-start+1))
    
    frameoffset = self._startFrame if self._startFrame else 0
    if hiero.core.isVideoFileExtension(os.path.splitext(self.resolvedExportPath())[1].lower()):
      frameoffset = 0
    self.originalItemTag.metadata().setValue("tag.frameoffset", str(frameoffset))

    # Note: if exporting without cut handles, i.e. the whole clip, we do not try to determine  the handle values,
    # just writing zeroes.  The build track classes need to treat this as a special case.
    # There is an interesting 'feature' of how tags work which means that if you create a Tag with a certain name,
    # the code tries to find a previously created instance with that name, which has any metadata keys that were set before.
    # This means that when multiple shots are being exported, they inherit the tag from the previous one.  To avoid problems
    # always set these keys.
    startHandle, endHandle = 0, 0
    if self._cutHandles:
      startHandle, endHandle = self.outputHandles()

    self.originalItemTag.metadata().setValue("tag.starthandle", str(startHandle))
    self.originalItemTag.metadata().setValue("tag.endhandle", str(endHandle))

    # Store if retimes were applied in the export.  Note that if self._cutHandles
    # is None, we are exporting the full clip and retimes are never applied whatever the
    # value of self._retime
    applyingRetime = (self._retime and self._cutHandles is not None)
    appliedRetimesStr = "1" if applyingRetime else "0"
    self.originalItemTag.metadata().setValue("tag.appliedretimes", appliedRetimesStr)

    self.originalItemTag.metadata().setValue("tag.frameio_upload_time", str(timestamp))

    self._tag_guid = self.originalItemTag.guid()

    originalItem.addTag(self.originalItemTag)

    self.originalItem = originalItem

    # The guid of the tag attached to the trackItem is different from the tag instace we created
    # Get the last tag in the list and store its guid
    #self._tag_guid = originalItem.tags()[-1].guid()

  """def finishTask (self):
    FnTranscodeExporter.TranscodeExporter.finishTask(self)

    if self.frameIOFileReference:
      print "Task Finished. Setting reference to be: self.frameIOFileReference"
      self.originalItemTag.setValue("tag.frameioRefernceID", str(self.frameIOFileReference))"""

  def finishTask(self):
    """
    Clean up after render.
    """
    # Close log file
    print "Finish Task"
    if self._logFile:
      FnTranscodeExporter.TranscodeExporter.finishTask(self)
    return


  def taskStep(self):
    # The parent implimentation of taskstep
    #  - Calls self.writeScript() which writes the script to the path in self._scriptfile
    #  - Executes script in Nuke with either HieroNuke or local Nuke as defined in preferences
    #  - Parses the output ever frame until complete
    if not self.uploadOnly:
      return FnTranscodeExporter.TranscodeExporter.taskStep(self)

    if self._finished:
      print "Transcode Finished!"

  def forcedAbort (self):
    # Parent impliementation terminates nuke process
    FnTranscodeExporter.TranscodeExporter.forcedAbort(self)    
    return


  def progress(self):
    """
    Get the render progress.
    TO-DO: Get the transcode+upload render progress.
    Progress is monitored by parsing frame progress in stdout from Nuke
    IF there is a transcode task, the progress goes from 0-0.5, the uploading continues from 0.5-1 
    If it is just an upload task, monitor the Upload    
    """
    if self._finished:
      return 1.0

    return float(FnTranscodeExporter.TranscodeExporter.progress(self))


class FrameioTranscodePreset(FnTranscodeExporter.TranscodePreset):
  def __init__(self, name, properties):
    FnTranscodeExporter.TranscodePreset.__init__(self, name, properties)
    self._parentType = FrameioTranscodeExporter

    # Set any preset defaults here
    self.properties()["keepNukeScript"] = False
    self.properties()["burninDataEnabled"] = False
    self.properties()["burninData"] = dict((datadict["knobName"], None) for datadict in NukeRenderTask.burninPropertyData)
    self.properties()["additionalNodesEnabled"] = False
    self.properties()["additionalNodesData"] = []
    self.properties()["method"] = "Blend"
    self.properties()["file_type"] = "mov"
    self.properties()["frameio_project"] = "NukeStudio"


    # Give the Write node a name, so it can be referenced elsewhere
    if "writeNodeName" not in self.properties():
      self.properties()["writeNodeName"] = "Write_{ext}"

    self.properties().update(properties)

  def supportedItems(self):
    return hiero.core.TaskPresetBase.kAllItems

hiero.core.taskRegistry.registerTask(FrameioTranscodePreset, FrameioTranscodeExporter)
