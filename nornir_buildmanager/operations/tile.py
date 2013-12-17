'''
Created on May 22, 2012

@author: Jamesan
'''

import math
import subprocess
import sys
import xml

from scipy.misc import imsave

from nornir_buildmanager import *
from nornir_buildmanager.VolumeManagerETree import *
from nornir_buildmanager.validation import transforms
import nornir_imageregistration.core as core
import nornir_imageregistration.image_stats as image_stats
from nornir_imageregistration.files import mosaicfile
from nornir_imageregistration.mosaic import Mosaic
from nornir_imageregistration.transforms import *
from nornir_shared import *
from nornir_shared.files import RemoveOutdatedFile
from nornir_shared.histogram import Histogram
from nornir_shared.misc import SortedListFromDelimited
import nornir_shared.plot


HistogramTagStr = "HistogramData"


# Shrinks the passed image file, return procedure handle of invoked command
def Shrink(Pool, InFile, OutFile, ShrinkFactor):
    Percentage = (1 / float(ShrinkFactor)) * 100.0
    cmd = "Convert " + InFile + " -scale \"" + str(Percentage) + "%\" -quality 106  -colorspace gray " + OutFile
    # prettyoutput.CurseString('Cmd', cmd)
    # NewP = subprocess.Popen(cmd + " && exit", shell=True)
    return Pool.add_process('Shrink: ' + InFile, cmd)


def VerifyImages(TilePyramidNode, **kwargs):
    '''Eliminate any image files which cannot be parsed by Image Magick's identify command'''
    logger = kwargs.get('Logger', None)

    if(logger is None):
        logger.error('VerifyImages. InputPyramidNode not found')
        return None

    PyramidLevels = nornir_shared.misc.SortedListFromDelimited(kwargs.get('Levels', [1, 2, 4, 8, 16, 32, 64, 128, 256]))

    Levels = TilePyramidNode.Levels
    LNodeSaveList = []
    for LNode in Levels:
        Downsample = int(LNode.attrib.get('Downsample', None))
        if not Downsample in PyramidLevels:
            continue

        LNode = VerifyTiles(LevelNode=LNode)
        if not LNode is None:
            LNodeSaveList.append(LNode)

    # Save the channelNode if a level node was changed
    if len(LNodeSaveList) > 0:
        return TilePyramidNode

    return None


def VerifyTiles(LevelNode=None, **kwargs):
    ''' @LevelNode
    Eliminate any image files which cannot be parsed by Image Magick's identify command
    '''
    logger = kwargs.get('Logger', logging.getLogger('VerifyTiles'))

    InputLevelNode = LevelNode
    TilesValidated = int(InputLevelNode.attrib.get('TilesValidated', 0))
    InputPyramidNode = InputLevelNode.FindParent('TilePyramid')
    TileExt = InputPyramidNode.attrib.get('ImageFormatExt', '.png')

    TileImageDir = InputLevelNode.FullPath
    LevelFiles = glob.glob(os.path.join(TileImageDir, '*' + TileExt))

    if(len(LevelFiles) == 0):
        logger.info('No tiles found in level')
        return None

    if TilesValidated == len(LevelFiles):
        logger.info('Tiles already validated')
        return None

    InvalidTiles = nornir_shared.images.IsValidImage(LevelFiles, TileImageDir)
    for InvalidTile in InvalidTiles:
        InvalidTilePath = os.path.join(TileImageDir, InvalidTile)
        if os.path.exists(InvalidTilePath):
            prettyoutput.LogErr('*** Deleting invalid tile: ' + InvalidTilePath)
            logger.warning('*** Deleting invalid tile: ' + InvalidTilePath)
            os.remove(InvalidTilePath)

    if len(InvalidTiles) == 0:
        logger.info('Tiles all valid')

    InputLevelNode.TilesValidated = len(LevelFiles) - len(InvalidTiles)

    return InputLevelNode


def FilterIsPopulated(InputFilterNode, Downsample, MosaicFullPath, OutputFilterName):

    ChannelNode = InputFilterNode.Parent
    InputChannelFullPath = ChannelNode.FullPath
    InputPyramidNode = InputFilterNode.find('TilePyramid')
    InputLevelNode = InputPyramidNode.GetChildByAttrib('Level', 'Downsample', Downsample)
    OutputFilterNode = ChannelNode.GetChildByAttrib('Filter', 'Name', OutputFilterName)
    if OutputFilterNode is None:
        return False

    OutputPyramidNode = OutputFilterNode.find('TilePyramid')
    if OutputPyramidNode is None:
        return False

    mFile = mosaicfile.MosaicFile.Load(MosaicFullPath)
    if OutputPyramidNode.NumberOfTiles < mFile.NumberOfImages:
        return False

    OutputLevelNode = OutputFilterNode.find("TilePyramid/Level[@Downsample='%g']" % Downsample)
    if OutputLevelNode is None:
        return False

    if not os.path.exists(OutputLevelNode.FullPath):
        return False

    # Find out if the number of predicted images matches the number of actual images
    ImageFiles = glob.glob(OutputLevelNode.FullPath + os.sep + '*' + InputPyramidNode.ImageFormatExt)
    basenameImageFiles = map(os.path.basename, ImageFiles)

    for i in mFile.ImageToTransformString:
        if not i in basenameImageFiles:
            # Don't return false unless the input exists
            if os.path.exists(os.path.join(InputLevelNode.FullPath, i)):
                return False

#    FileCountEqual = len(ImageFiles) == OutputPyramidNode.NumberOfTiles
#    return   FileCountEqual
    return True


def EvaluateImageList(ImageList, CmdTemplate):
    # FileList = list()
    OutputNumber = 0
    TempFileList = []

    CmdLineFileList = ""
    while len(TempFileList) == 0 and CmdLineFileList == "":

        # First we process all of the original tiles.  We can't run them all because Windows has command line length limits.  I haven't tried passing the arguments as an array though...
        if(len(ImageList) > 0):
            while len(ImageList) > 0:
                # basefilename = os.path.basename(tilefullpath)
            #    FileList.append(basefilename)
            #    CmdList.append(basefilename)
                if(len(CmdLineFileList) + len(ImageList[0]) < 900):
                    TileFileName = ImageList.pop()
                    CmdLineFileList = CmdLineFileList + ' ' + os.path.basename(str(TileFileName))
                else:
                    break

        # This only runs after we've processed all of the original tiles
        elif(len(TempFileList) > 1):
            while len(TempFileList) > 1:
                if(len(CmdLineFileList) + len(TempFileList[0]) < 900):
                    CmdLineFileList = CmdLineFileList + ' ' + str(TempFileList[0])
                    del TempFileList[0]
                else:
                    break

        TempFinalTarget = os.path.join(Path, 'Temp' + str(OutputNumber) + '.png')
        OutputNumber = OutputNumber + 1
        ImageList.append(TempFinalTarget)
        TempFileList.append(TempFinalTarget)

        # CmdList.append(FileList)
#        CmdList.append(PreEvaluateSequenceArg)
#        CmdList.append("-evaluate-sequence")
#        CmdList.append(EvaluateSequenceArg)
#        CmdList.append(PostEvaluateSequenceArg)
#        CmdList.append(FinalTarget)

        Cmd = CmdBase % {'Images' : CmdLineFileList,
                          'PreEvaluateSequenceArg' : PreEvaluateSequenceArg,
                          'EvaluateSequenceArg' :  EvaluateSequenceArg,
                          'OutputFile' : TempFinalTarget}

        prettyoutput.Log(Cmd)
        subprocess.call(Cmd + " && exit", shell=True, cwd=TileDir)
        CmdLineFileList = ""


def Evaluate(Parameters, FilterNode, OutputImageName=None, Level=1, PreEvaluateSequenceArg=None, EvaluateSequenceArg=None, PostEvaluateSequenceArg=None, **kwargs):
    PyramidNode = FilterNode.find('TilePyramid')
    assert(not PyramidNode is None)
    levelNode = PyramidNode.GetChildByAttrib('Level', 'Downsample', Level)
    assert(not levelNode is None)

    if PreEvaluateSequenceArg is None:
        PreEvaluateSequenceArg = ''

    if EvaluateSequenceArg is None:
        EvaluateSequenceArg = ''

    if OutputImageName is None:
        OutputImageName = EvaluateSequenceArg

    assert(not OutputImageName is None)

    FinalTargetPath = OutputImageName + PyramidNode.ImageFormatExt
    PreFinalTargetPath = 'Pre-' + OutputImageName + PyramidNode.ImageFormatExt

    PreFinalTargetFullPath = os.path.join(FilterNode.FullPath, PreFinalTargetPath)

    OutputImageNode = FilterNode.GetChildByAttrib('Image', 'Name', OutputImageName)
    if not OutputImageNode is None:
        if OutputImageNode.CleanIfInvalid():
            OutputImageNode = None

    # Find out if the output image node exists already
    OutputImageNode = VolumeManagerETree.ImageNode(Path=FinalTargetPath, attrib={'Name' : OutputImageName})
    (ImageNodeCreated, OutputImageNode) = FilterNode.UpdateOrAddChildByAttrib(OutputImageNode, 'Name')

    prettyoutput.CurseString('Stage', FilterNode.Name + " ImageMagick -Evaluate-Sequence " + EvaluateSequenceArg)

    CmdTemplate = "convert %(Images)s %(PreEvaluateSequenceArg)s -evaluate-sequence %(EvaluateSequenceArg)s %(OutputFile)s"

    TileFullPath = os.path.join(levelNode.FullPath, '*' + PyramidNode.ImageFormatExt)


    Cmd = CmdTemplate % {'Images' : TileFullPath,
                             'PreEvaluateSequenceArg' : PreEvaluateSequenceArg,
                             'EvaluateSequenceArg' :  EvaluateSequenceArg,
                             'OutputFile' : PreFinalTargetFullPath}

    prettyoutput.Log(Cmd)
    subprocess.call(Cmd + " && exit", shell=True)

    if not PostEvaluateSequenceArg is None:
        PostCmd = 'convert ' + PreFinalTargetFullPath + ' ' + PostEvaluateSequenceArg + ' ' + OutputImageNode.FullPath
        prettyoutput.Log(Cmd)
        proc = subprocess.call(PostCmd + " && exit", shell=True)
        os.remove(PreFinalTargetFullPath)
    else:
        shutil.move(PreFinalTargetFullPath, OutputImageNode.FullPath)

    if ImageNodeCreated:
        return FilterNode

    return None


def CreateMinCorrectionImage(ImageNode, OutputImageName, **kwargs):
    '''Creates an image from the source image whose min pixel value is zero'''

    ParentNode = ImageNode.Parent
    OutputFile = OutputImageName + ".png"

    # Find out if the output image node exists already
    OutputImageNode = VolumeManagerETree.ImageNode(Path=OutputFile, attrib={'Name' : OutputImageName})
    (ImageNodeCreated, OutputImageNode) = ParentNode.UpdateOrAddChildByAttrib(OutputImageNode, 'Name')

    nornir_shared.files.RemoveOutdatedFile(ImageNode.FullPath, OutputImageNode.FullPath)

    if os.path.exists(OutputImageNode.FullPath):
        return OutputImageNode

    [Min, Mean, Max, StdDev] = nornir_shared.images.GetImageStats(ImageNode.FullPath)

    # Temp file with a uniform value set to the minimum pixel value of ImageNode
    OutputFileUniformFullPath = os.path.join(ParentNode.FullPath, 'UniformMinBackground_' + OutputFile)
    CreateBackgroundCmdTemplate = 'convert %(OperatorImage)s  +matte -background "gray(%(BackgroundIntensity)f)" -compose Dst -flatten %(OutputFile)s'
    CreateBackgroundCmd = CreateBackgroundCmdTemplate % {'OperatorImage': ImageNode.FullPath,
                                                         'BackgroundIntensity': float(Min / 256),  # TODO This only works for 8-bit
                                                         'OutputFile' : OutputFileUniformFullPath}
    prettyoutput.Log(CreateBackgroundCmd)
    subprocess.call(CreateBackgroundCmd + " && exit", shell=True)

    # Create the zerod image
    CmdBase = "convert %(OperatorImage)s %(InputFile)s %(InvertOperator)s -compose %(ComposeOperator)s -composite %(OutputFile)s"
    CreateZeroedImageCmd = CmdBase % {'OperatorImage' : OutputFileUniformFullPath,
                                      'InputFile' :  ImageNode.FullPath,
                                      'InvertOperator' : '',
                                      'ComposeOperator' : 'minus_Dst',
                                      'OutputFile' : OutputImageNode.FullPath}

    prettyoutput.Log(CreateZeroedImageCmd)
    subprocess.call(CreateZeroedImageCmd + " && exit", shell=True)

    return OutputImageNode


def CorrectTiles(Parameters, FilterNode=None, ImageNode=None, OutputFilterName=None, InvertSource=False, ComposeOperator=None, **kwargs):
    '''Create a corrected version of a filter by applying the operation/image to all tiles'''

    assert(not FilterNode is None)
    InputPyramidNode = FilterNode.find('TilePyramid')
    assert(not InputPyramidNode is None)

    InputLevelNode = InputPyramidNode.MaxResLevel
    assert(not InputLevelNode is None)

    assert(not ImageNode is None)

    if ComposeOperator is None:
        ComposeOperator = 'minus'

    InvertOperator = ''
    if(not InvertSource is None):
        InvertOperator = '-negate'

    FilterParent = FilterNode.Parent

    SaveFilterParent = False

    # Find out if the output filter already exists
    [SaveFilterParent, OutputFilterNode] = FilterParent.UpdateOrAddChildByAttrib(VolumeManagerETree.XContainerElementWrapper('Filter',
                                                                                                                         OutputFilterName,
                                                                                                                         OutputFilterName))
    OutputFilterNode.BitsPerPixel = FilterNode.BitsPerPixel

    # Check if the output node exists
    OutputPyramidNode = VolumeManagerETree.TilePyramidNode(Type=InputPyramidNode.Type,
                                                           NumberOfTiles=InputPyramidNode.NumberOfTiles,
                                                           LevelFormat=InputPyramidNode.LevelFormat,
                                                           ImageFormatExt=InputPyramidNode.ImageFormatExt)

    [added, OutputPyramidNode] = OutputFilterNode.UpdateOrAddChildByAttrib(OutputPyramidNode, 'Path')

    OutputLevelNode = VolumeManagerETree.LevelNode(Level=InputLevelNode.Downsample)
    [OutputLevelAdded, OutputLevelNode] = OutputPyramidNode.UpdateOrAddChildByAttrib(OutputLevelNode, 'Downsample')

    # Make sure the destination directory exists
    if not os.path.exists(OutputLevelNode.FullPath):
        os.makedirs(OutputLevelNode.FullPath)


    CmdTemplate = "convert %(OperatorImage)s %(InputFile)s %(InvertOperator)s -compose %(ComposeOperator)s -composite %(OutputFile)s"

    InputTiles = glob.glob(os.path.join(InputLevelNode.FullPath, '*' + InputPyramidNode.ImageFormatExt))

    ZeroedImageNode = CreateMinCorrectionImage(ImageNode, 'Zeroed' + ImageNode.Name)

    Pool = Pools.GetGlobalClusterPool()

    for InputTileFullPath in InputTiles:
        inputTile = os.path.basename(InputTileFullPath)
        OutputTileFullPath = os.path.join(OutputLevelNode.FullPath, inputTile)

        RemoveOutdatedFile(InputTileFullPath, OutputTileFullPath)

        if os.path.exists(OutputTileFullPath):
            continue

        Cmd = CmdTemplate % {'OperatorImage' : ImageNode.FullPath,
                             'InputFile' :  InputTileFullPath,
                             'InvertOperator' : InvertOperator,
                             'ComposeOperator' : ComposeOperator,
                             'OutputFile' : OutputTileFullPath}
        prettyoutput.Log(Cmd)
        Pool.add_process(inputTile, Cmd + " && exit", shell=True)

    Pool.wait_completion()

    if SaveFilterParent:
        return FilterParent

    return FilterNode



def AutolevelTiles(Parameters, LevelNode=None, TransformNode=None, OutputFilterName=None, **kwargs):
    '''Create a new filter using the histogram of the input filter
       @ChannelNode'''

    InputLevelNode = LevelNode
    InputTransformNode = TransformNode
    InputPyramidNode = InputLevelNode.FindParent('TilePyramid')
    InputFilterNode = InputPyramidNode.FindParent('Filter')

    ChannelNode = InputFilterNode.Parent

    if OutputFilterName is None:
        OutputFilterName = 'Leveled'

    HistogramElement = InputFilterNode.find("Histogram[@InputTransformChecksum='" + InputTransformNode.Checksum + "']")
    assert(not HistogramElement is None)

    AutoLevelDataNode = HistogramElement.find('AutoLevelHint')
    MinIntensityCutoff = AutoLevelDataNode.UserRequestedMinIntensityCutoff
    MaxIntensityCutoff = AutoLevelDataNode.UserRequestedMaxIntensityCutoff
    UserRequestedGamma = AutoLevelDataNode.UserRequestedGamma

    MinCutoffPercent = float(Parameters.get('MinCutoff', 0.1)) / 100.0
    MaxCutoffPercent = float(Parameters.get('MaxCutoff', 0.5)) / 100.0

    Gamma = Parameters.get('Gamma', None)
    if not UserRequestedGamma is None:
        Gamma = UserRequestedGamma

    if isinstance(Gamma, str):
        if Gamma == 'None':
            Gamma = None

    if not Gamma is None:
        try:
            Gamma = float(Gamma)
        except:
            prettyoutput.LogErr("Invalid gamma value passed to AutoLevel function: " + str(Gamma))
            Gamma = None

    InputMosaicFullPath = InputTransformNode.FullPath

    # If the output filter already exists, find out if the user has specified the min and max pixel values explicitely.
    OutputFilterNode = None
    if FilterIsPopulated(InputFilterNode, InputLevelNode.Downsample, InputTransformNode.FullPath, OutputFilterName):
        OutputFilterNode = ChannelNode.GetChildByAttrib('Filter', 'Name', OutputFilterName)

    # Calculate min or max pixel values if they are needed
    # The bummer here is we always load the histogram file to check that the filter levels are correct
    if MinIntensityCutoff is None or MaxIntensityCutoff is None or Gamma is None:

        # Check if we've already created the filter before loading files.  It saves a lot of time
        histogram = Histogram.Load(HistogramElement.DataFullPath)

        if histogram is None:
            prettyoutput.LogErr("*** No histogram data found to create filter with: " + HistogramElement.DataFullPath + "***")
            return

        if MinIntensityCutoff is None or MaxIntensityCutoff is None:
            [CalculatedMinCutoff, CalculatedMaxCutoff] = histogram.AutoLevel(MinCutoffPercent, MaxCutoffPercent)

            if(int(InputFilterNode.BitsPerPixel) == 8):
                if MinIntensityCutoff is None:
                    MinIntensityCutoff = int(round(CalculatedMinCutoff))
                if MaxIntensityCutoff is None:
                    MaxIntensityCutoff = int(round(CalculatedMaxCutoff))

        if MinIntensityCutoff > MaxIntensityCutoff:
            prettyoutput.LogErr("Max intensity is less than min intensity for histogram correction")
            return None

        if Gamma is None:
            Gamma = histogram.GammaAtValue(histogram.Median, minVal=MinIntensityCutoff, maxVal=MaxIntensityCutoff)

    OutputFilterNode = transforms.RemoveOnMismatch(OutputFilterNode, 'MinIntensityCutoff', MinIntensityCutoff)
    OutputFilterNode = transforms.RemoveOnMismatch(OutputFilterNode, 'MaxIntensityCutoff', MaxIntensityCutoff)
    OutputFilterNode = transforms.RemoveOnMismatch(OutputFilterNode, 'Gamma', Gamma, 3)

    if not OutputFilterNode is None:
        # Nothing to do
        return None

    # TODO: Verify parameters match... if(OutputFilterNode.Gamma != Gamma)
    DictAttributes = {'BitsPerPixel' : 8,
                                                                                                        'MinIntensityCutoff' : str(MinIntensityCutoff),
                                                                                                        'MaxIntensityCutoff' : str(MaxIntensityCutoff),
                                                                                                        'Gamma' : str(Gamma),
                                                                                                        'HistogramChecksum' : str(HistogramElement.Checksum)}

    [Created, OutputFilterNode] = ChannelNode.UpdateOrAddChildByAttrib(VolumeManagerETree.XContainerElementWrapper('Filter',
                                                                                                                         OutputFilterName,
                                                                                                                         OutputFilterName,
                                                                                                                         DictAttributes))

#    if not (int(float(OutputFilterNode.MinIntensityCutoff)) == int(AutoLevelDataNode.UserRequestedMinIntensityCutoff) and
#           int(float(OutputFilterNode.MaxIntensityCutoff)) == int(AutoLevelDataNode.UserRequestedMaxIntensityCutoff) ):
#        shutil.rmtree(OutputFilterNode.FullPath)
#        OutputFilterNode.MinIntensityCutoff = AutoLevelDataNode.UserRequestedMinIntensityCutoff
#        OutputFilterNode.MaxIntensityCutoff = AutoLevelDataNode.UserRequestedMaxIntensityCutoff

    if not os.path.exists(OutputFilterNode.FullPath):
        os.makedirs(OutputFilterNode.FullPath)

    Input = mosaicfile.MosaicFile.Load(InputMosaicFullPath)
    ImageFiles = Input.ImageToTransformString.keys()

    InputImagePath = InputLevelNode.FullPath

    OutputPyramidNode = VolumeManagerETree.TilePyramidNode(Type=InputPyramidNode.Type,
                                                           NumberOfTiles=InputPyramidNode.NumberOfTiles,
                                                           LevelFormat=InputPyramidNode.LevelFormat,
                                                           ImageFormatExt=InputPyramidNode.ImageFormatExt)
    [added, OutputPyramidNode] = OutputFilterNode.UpdateOrAddChildByAttrib(OutputPyramidNode, 'Path')

    OutputLevelNode = VolumeManagerETree.LevelNode(Level=InputLevelNode.Downsample)
    [added, OutputLevelNode] = OutputPyramidNode.UpdateOrAddChildByAttrib(OutputLevelNode, 'Downsample')

    OutputImagePath = OutputLevelNode.FullPath

    TilesToBuild = list()

    # Make sure output isn't outdated
    OutputDirIsEmpty = False
    if(not os.path.exists(OutputImagePath)):
        os.makedirs(OutputImagePath)
        OutputDirIsEmpty = True

    for tile in ImageFiles:
        InputTile = os.path.join(InputImagePath, tile)
        if OutputDirIsEmpty:
            TilesToBuild.append(InputTile)
            continue
        else:
            PredictedOutput = os.path.join(OutputImagePath, os.path.basename(tile))
            RemoveOutdatedFile(InputTile, PredictedOutput)
            if not os.path.exists(PredictedOutput):
                TilesToBuild.append(InputTile)

    Pool = None
    if len(TilesToBuild) > 0:
        Pool = Pools.GetGlobalClusterPool()

    MinIntensityCutoff16bpp = MinIntensityCutoff * 256
    MaxIntensityCutoff16bpp = MaxIntensityCutoff * 256

    # In case the user swaps min/max cutoffs swap these values if needed
    if MaxIntensityCutoff16bpp < MinIntensityCutoff16bpp:
        temp = MaxIntensityCutoff16bpp
        MaxIntensityCutoff16bpp = MinIntensityCutoff16bpp
        MinIntensityCutoff16bpp = temp

    SampleCmdPrinted = False

    for imageFile in TilesToBuild:
        InputImageFullPath = os.path.join(InputLevelNode.FullPath, imageFile)
        ImageSaveFilename = os.path.join(OutputImagePath, os.path.basename(imageFile))

        cmd = 'convert \"' + InputImageFullPath + '\" ' + \
               '-level ' + str(MinIntensityCutoff16bpp) + \
               ',' + str(MaxIntensityCutoff16bpp) + \
               ' -gamma ' + str(Gamma) + \
               ' -colorspace Gray -depth 8 -type optimize ' + \
               ' \"' + ImageSaveFilename + '\"'


        if not SampleCmdPrinted:
            SampleCmdPrinted = True
            prettyoutput.CurseString('Cmd', cmd)
        Pool.add_process('AutoLevel: ' + cmd, cmd)

    if not Pool is None:
        Pool.wait_completion()

    OutputPyramidNode.NumberOfTiles = len(ImageFiles)

    # Save the channel node so the new filter is recorded
    return ChannelNode


def TranslateToZeroOrigin(ChannelNode, TransformNode, OutputTransformName, Logger, **kwargs):
    ''' @ChannelNode  '''

    outputFilename = OutputTransformName + ".mosaic"
    outputFileFullPath = os.path.join(os.path.dirname(TransformNode.FullPath), outputFilename)

    OutputTransformNode = TransformNode.Parent.GetChildByAttrib('Transform', 'Path', outputFilename)
    OutputTransformNode = transforms.RemoveIfOutdated(OutputTransformNode, TransformNode, Logger)

    if os.path.exists(outputFileFullPath) and (not OutputTransformNode is None):
        return None

    prettyoutput.Log("Moving origin to 0,0 - " + TransformNode.FullPath)

    mosaic = mosaicfile.MosaicFile.Load(TransformNode.FullPath)

    # Find the min,max values from all of the transforms
    minX = float('Inf')
    minY = float('Inf')
    maxX = -float('Inf')
    maxY = -float('Inf')

    Transforms = {}
    for imagename, transform in mosaic.ImageToTransformString.iteritems():
        MosaicToSectionTransform = factory.LoadTransform(transform)
        Transforms[imagename] = MosaicToSectionTransform
        bbox = MosaicToSectionTransform.ControlPointBoundingBox

        minX = min(minX, bbox[0])
        minY = min(minY, bbox[1])
        maxX = max(maxX, bbox[2])
        maxY = max(maxY, bbox[3])

    if OutputTransformNode is None:
        OutputTransformNode = copy.deepcopy(TransformNode)
        OutputTransformNode.Path = outputFilename
        OutputTransformNode.Name = OutputTransformName
        OutputTransformNode.InputTransform = TransformNode.Name
        [SaveRequired, OutputTransformNode] = TransformNode.Parent.UpdateOrAddChildByAttrib(OutputTransformNode, 'Path')
    else:
        OutputTransformNode.Path = outputFilename
        OutputTransformNode.Name = OutputTransformName
        OutputTransformNode.InputTransform = TransformNode.Name

    OutputTransformNode.InputTransformChecksum = TransformNode.Checksum

    Logger.info("Translating mosaic: " + str(minX) + ", " + str(minY) + "\t\t" + TransformNode.FullPath)

    # Adjust all of the control points such that the origin is at 0,0
    for imagename in Transforms.keys():
        transform = Transforms[imagename]
        transform.TranslateFixed((-minY, -minX))
        mosaic.ImageToTransformString[imagename] = factory.TransformToIRToolsGridString(transform, transform.gridWidth, transform.gridHeight)


    mosaic.Save(OutputTransformNode.FullPath)
    OutputTransformNode.attrib['Checksum'] = mosaic.Checksum

    return ChannelNode


def HistogramFilter(Parameters, FilterNode, LevelNode, TransformNode, **kwargs):
    '''Construct the intensity histogram for a filter
       @FilterNode'''
    NodeToSave = None

    InputOverlap = Parameters.get('Overlap', 0.1)
    InputLevel = Parameters.get('Level', 1)

    if(LevelNode is None):
        prettyoutput.LogErr("Missing InputPyramidLevelNode attribute on PruneTiles")
        return None

    if(TransformNode is None):
        prettyoutput.LogErr("Missing TransformNode attribute on PruneTiles")
        return None

    InputMosaicFullPath = TransformNode.FullPath
    FilterNode = LevelNode.FindParent('Filter')

    MangledName = nornir_shared.misc.GenNameFromDict(Parameters) + TransformNode.Type
    HistogramBaseName = "Histogram" + MangledName
    OutputHistogramXmlFilename = HistogramBaseName + ".xml"
    OutputHistogramPngFilename = HistogramBaseName + ".png"

    HistogramElement = VolumeManagerETree.HistogramNode(TransformNode, Type=MangledName, attrib=Parameters)
    [HistogramElementCreated, HistogramElement] = FilterNode.UpdateOrAddChildByAttrib(HistogramElement, "Type")

    if not HistogramElementCreated and HistogramElement.InputTransformChecksum != TransformNode.Checksum:
        logging.info("Cleaned outdated element: " + str(HistogramElement))
        HistogramElement.Clean()
        HistogramElement = VolumeManagerETree.HistogramNode(TransformNode, Type=MangledName, attrib=Parameters)
        [HistogramElementCreated, HistogramElement] = FilterNode.UpdateOrAddChildByAttrib(HistogramElement, "Type")

    if HistogramElementCreated:
        NodeToSave = FilterNode

    ImageNode = VolumeManagerETree.ImageNode(OutputHistogramPngFilename)
    [added, ImageNode] = HistogramElement.UpdateOrAddChild(ImageNode)
#
    DataNode = VolumeManagerETree.DataNode(OutputHistogramXmlFilename)
    [added, DataNode] = HistogramElement.UpdateOrAddChild(DataNode)

    AutoLevelDataNode = HistogramElement.find('AutoLevelHint')
    # Create an AutoLevelData node to give hints to other filters regarding how this data should be contrast adjusted
    if AutoLevelDataNode is None:

        # TEMP, check if this is an element with old formatting
        AutoLevelDataNode = FilterNode.find('AutoLevelHint')
        if AutoLevelDataNode is None:
            # Create a new AutoLevelData node using the calculated values as overrides so users can find and edit it later
            AutoLevelDataNode = VolumeManagerETree.AutoLevelHintNode()
            [added, AutoLevelDataNode] = HistogramElement.UpdateOrAddChild(AutoLevelDataNode)
        else:
            FilterNode.remove(AutoLevelDataNode)
            HistogramElement.append(AutoLevelDataNode)

    if os.path.exists(HistogramElement.DataFullPath) and os.path.exists(HistogramElement.ImageFullPath) and HistogramElement.InputTransformChecksum == TransformNode.Checksum:
        return NodeToSave



    NodeToSave = FilterNode
    # Check the folder for changes, not the .mosaic file
    # RemoveOutdatedFile(TransformNode.FullPath, OutputHistogramXmlFullPath)
    # RemoveOutdatedFile(TransformNode.FullPath, OutputHistogramPngFilename)

    Bpp = 16
    if(not FilterNode.BitsPerPixel is None):
        Bpp = int(FilterNode.BitsPerPixel)

    NumBins = 2 << Bpp
    if(NumBins > 2048):
        NumBins = 2048

        HistogramElement.append(AutoLevelDataNode)

    if not os.path.exists(DataNode.FullPath):
        mosaic = mosaicfile.MosaicFile.Load(InputMosaicFullPath)

        FullTilePath = LevelNode.FullPath
        fulltilepaths = list()
        for k in mosaic.ImageToTransformString.keys():
            fulltilepaths.append(os.path.join(FullTilePath, k))

        histogramObj = image_stats.Histogram(fulltilepaths, Bpp=Bpp)
        histogramObj.Save(DataNode.FullPath)

        # Create a data node for the histogram
        # DataObj = VolumeManagerETree.DataNode(Path=)

        if os.path.exists(ImageNode.FullPath):
            os.remove(ImageNode.FullPath)

    if not os.path.exists(ImageNode.FullPath):

        MinCutoffPercent = Parameters.get('MinCutoff', 0.005)
        MaxCutoffPercent = Parameters.get('MaxCutoff', 0.005)
        LinePositions = []
        if not AutoLevelDataNode.UserRequestedMinIntensityCutoff is None:
            MinCutoffLine = float(AutoLevelDataNode.UserRequestedMinIntensityCutoff)
            LinePositions.append(MinCutoffLine)
            MinCutoffPercent = None

        if not AutoLevelDataNode.UserRequestedMinIntensityCutoff is None:
            MaxCutoffLine = float(AutoLevelDataNode.UserRequestedMaxIntensityCutoff)
            LinePositions.append(MaxCutoffLine)
            MaxCutoffPercent = None

        ChannelNode = FilterNode.FindParent('Channel')
        SectionNode = ChannelNode.FindParent('Section')

        TitleStr = str(SectionNode.Number) + " " + ChannelNode.Name + " " + FilterNode.Name + " histogram"

        prettyoutput.Log("Creating Section Autoleveled Histogram Image: " + DataNode.FullPath)
        nornir_shared.plot.Histogram(DataNode.FullPath, ImageNode.FullPath, MinCutoffPercent, MaxCutoffPercent, LinePosList=LinePositions, Title=TitleStr)

    HistogramElement.InputTransformChecksum = TransformNode.Checksum

    return NodeToSave


def BuildTilePyramids(PyramidNode=None, Levels=None, **kwargs):
    ''' @PyramidNode
        Build the image pyramid for the specified path.  We expect the "001" level of the pyramid to be pre-populated'''
    prettyoutput.CurseString('Stage', "BuildPyramids")

    SavePyramidNode = False

    if Levels is None:
        Levels = [1, 2, 4, 8, 16, 32, 64, 128, 256]

    PyramidLevels = nornir_shared.misc.SortedListFromDelimited(Levels)
    Extension = 'png'

    Pool = None

    if(PyramidNode is None):
        prettyoutput.LogErr("No volume element available for BuildTilePyramids")
        return

    LevelFormatStr = PyramidNode.attrib.get('LevelFormat', Config.Current.LevelFormat)

    InputPyramidFullPath = PyramidNode.FullPath

    prettyoutput.Log("Checking path for unbuilt pyramids: " + InputPyramidFullPath)

    for i in range(1, len(PyramidLevels)):

        LevelHeaderPrinted = False

        upLevel = PyramidLevels[i - 1]
        thisLevel = PyramidLevels[i]

        upLevelPathStr = LevelFormatStr % upLevel
        thisLevePathlStr = LevelFormatStr % thisLevel

        shrinkFactor = float(thisLevel) / float(upLevel)

        upLevelNode = VolumeManagerETree.LevelNode(upLevel)
        [LevelNodeCreated, upLevelNode] = PyramidNode.UpdateOrAddChildByAttrib(upLevelNode, "Downsample")
        if LevelNodeCreated:
            SavePyramidNode = True

        thisLevelNode = VolumeManagerETree.LevelNode(thisLevel)
        [LevelNodeCreated, thisLevelNode] = PyramidNode.UpdateOrAddChildByAttrib(thisLevelNode, "Downsample")
        if LevelNodeCreated:
            SavePyramidNode = True

        InputTileDir = os.path.join(InputPyramidFullPath, upLevelPathStr)
        OutputTileDir = os.path.join(InputPyramidFullPath, thisLevePathlStr)

        InputGlobPattern = os.path.join(InputTileDir, "*." + Extension)
        OutputGlobPattern = os.path.join(OutputTileDir, "*." + Extension)

        SourceFiles = glob.glob(InputGlobPattern)

        taskList = []

        # Create directories if we have source files and the directories are missing
        if(len(SourceFiles) > 0):
            if not os.path.exists(OutputTileDir):
                os.makedirs(OutputTileDir)

        # Simply a speedup so we aren't constantly hitting the server with exist requests for populated directories
        DestFiles = glob.glob(OutputGlobPattern)
        if(len(DestFiles) == PyramidNode.NumberOfTiles and
           len(SourceFiles) == len(DestFiles)):
            continue

        DestFiles = [os.path.basename(x) for x in DestFiles ]

        for f in SourceFiles:
            filename = os.path.basename(f)

            outputFile = os.path.join(OutputTileDir, filename)
            inputFile = os.path.join(InputTileDir, filename)

            if(filename in DestFiles):
                continue

            # Don't process if the input is temp file
            try:
                if(os.path.getsize(inputFile) <= 0):
                    continue
            except:
                continue

            RemoveOutdatedFile(inputFile, outputFile)

            if(os.path.exists(outputFile)):
                continue

            if Pool is None:
                Pool = Pools.GetGlobalClusterPool()

            if not LevelHeaderPrinted:
       #         prettyoutput.Log(str(upLevel) + ' -> ' + str(thisLevel) + '\n')
                LevelHeaderPrinted = True

            task = Shrink(Pool, inputFile, outputFile, shrinkFactor)
            task.inputFile = inputFile
            taskList.append(task)

        if not Pool is None:
            Pool.wait_completion()

            for task in taskList:
                if task.returncode > 0:
                    prettyoutput.LogErr('\n*** Suspected bad input file to pyramid, deleting the source image.  Rerun scripts to attempt adding the file again.\n')
                    try:
                        os.remove(task.inputFile)
                    except:
                        pass

    if SavePyramidNode:
        return PyramidNode

    return None

# def UpdateNode(Parameters, Logger, Node):
 #    '''This is a placeholder for patching up volume.xml files on a case-by-case basis'''
    # return


def MigrateMultipleImageSets(FilterNode, Logger, **kwargs):
    '''Temp function to migrate the mask from the old layout with masks not having a separate filter.'''

    ChannelNode = FilterNode.Parent
    ImageSets = list(FilterNode.findall('ImageSet'))

    if(len(ImageSets) < 1):
        return None

    MigrationOccurred = False

    for isetNode in ImageSets:

        originalName = isetNode.Name.lower()

        if originalName == ImageSetNode.DefaultName:
            continue

        Logger.warn("Outdated ImageSet %s found in FilterNode.  Migrating..." % originalName)
        MigrationOccurred = True

        OldPath = isetNode.FullPath

        isetNode.Name = ImageSetNode.DefaultName
        isetNode.Path = ImageSetNode.DefaultPath

        # Create a mask filter for this imageset
        ChannelNode = FilterNode.Parent

        NewFilterNode = None
        if 'mask' in originalName:
            NewFilterNode = FilterNode.GetOrCreateMaskFilter(FilterNode.MaskName)
        elif not 'assemble' in originalName:
            NewFilterNode = ChannelNode.GetOrCreateFilter(originalName)
        else:
            if hasattr(isetNode, 'MaskName'):
                del isetNode.MaskName

        # We use assemble as the old default imageset name for a filter to prevent a filter with no imagesets being left behind
        if not NewFilterNode is None:
            FilterNode.remove(isetNode)
            NewFilterNode.append(isetNode)
            isetNode.Parent = NewFilterNode

        NewPath = isetNode.FullPath

        if os.path.exists(NewPath):
            os.removedirs(NewPath)

        Logger.warn("Moving: " + OldPath + "\n-> " + NewPath)
        shutil.move(OldPath, NewPath)

    if MigrationOccurred:
        return ChannelNode

    return None
    # return MigrationOccurred


def AssembleTransform(Parameters, Logger, ChannelNode, PyramidNode, TransformNode, ThumbnailSize=256, Interlace=True, **kwargs):
    return AssembleTransformScipy(Parameters, Logger, ChannelNode, PyramidNode, TransformNode, ThumbnailSize=256, Interlace=True, **kwargs)


def AssembleTransformScipy(Parameters, Logger, ChannelNode, PyramidNode, TransformNode, UseCluster=False, ThumbnailSize=256, Interlace=True, **kwargs):
    '''@ChannelNode - TransformNode lives under ChannelNode'''
    Feathering = Parameters.get('Feathering', 'binary')

    FilterNode = PyramidNode.FindParent('Filter')
    MaskFilterNode = FilterNode.GetOrCreateMaskFilter(FilterNode.MaskName)
    # ChannelNode = FilterNode.FindParent('Channel')
    SectionNode = ChannelNode.FindParent('Section')

    NodesToSave = []

    MangledName = misc.GenNameFromDict(Parameters) + TransformNode.Type

    PyramidLevels = SortedListFromDelimited(kwargs.get('Levels', [1, 2, 4, 8, 16, 32, 64, 128, 256]))

    OutputImageNameTemplate = Config.Current.SectionTemplate % SectionNode.Number + "_" + ChannelNode.Name + "_" + FilterNode.Name + ".png"
    OutputImageMaskNameTemplate = Config.Current.SectionTemplate % SectionNode.Number + "_" + ChannelNode.Name + "_" + MaskFilterNode.Name + ".png"

    FilterNode.Imageset.SetTransform(TransformNode)
    MaskFilterNode.Imageset.SetTransform(TransformNode)

    argstring = misc.ArgumentsFromDict(Parameters)
    irassembletemplate = 'ir-assemble ' + argstring + ' -sh 1 -sp %(pixelspacing)i -save %(OutputImageFile)s -load %(InputFile)s -mask %(OutputMaskFile)s -image_dir %(ImageDir)s '

    LevelFormatTemplate = PyramidNode.attrib.get('LevelFormat', Config.Current.LevelFormat)

    thisLevel = PyramidLevels[0]

    # Create a node for this level
    ImageLevelNode = FilterNode.Imageset.GetOrCreateLevel(thisLevel)
    ImageMaskLevelNode = MaskFilterNode.Imageset.GetOrCreateLevel(thisLevel)

    if not os.path.exists(ImageLevelNode.FullPath):
        os.makedirs(ImageLevelNode.FullPath)

    if not os.path.exists(ImageMaskLevelNode.FullPath):
        os.makedirs(ImageMaskLevelNode.FullPath)

    thisLevelPathStr = OutputImageNameTemplate % {'level' : thisLevel,
                                                  'transform' : TransformNode.Name}
    thisLevelMaskPathStr = OutputImageMaskNameTemplate % {'level' : thisLevel,
                                                  'transform' : TransformNode.Name}

    ImageName = Config.Current.SectionTemplate % SectionNode.Number + "_" + kwargs.get('ImageName', 'assemble')

    # Should Replace any child elements
    ImageNode = ImageLevelNode.find('Image')
    if(ImageNode is None):
        ImageNode = VolumeManagerETree.ImageNode(OutputImageNameTemplate)
        ImageLevelNode.append(ImageNode)

    MaskImageNode = ImageMaskLevelNode.find('Image')
    if(MaskImageNode is None):
        MaskImageNode = VolumeManagerETree.ImageNode(OutputImageMaskNameTemplate)
        ImageMaskLevelNode.append(MaskImageNode)

    ImageNode.MaskPath = MaskImageNode.FullPath

    if not (os.path.exists(ImageNode.FullPath) and os.path.exists(MaskImageNode.FullPath)):

        LevelFormatStr = LevelFormatTemplate % thisLevel
        ImageDir = os.path.join(PyramidNode.FullPath, LevelFormatStr)

        tempOutputFullPath = os.path.join(ImageDir, 'Temp.png')
        tempMaskOutputFullPath = os.path.join(ImageDir, 'TempMask.png')

        Logger.info("Assembling " + TransformNode.FullPath)
        mosaic = Mosaic.LoadFromMosaicFile(TransformNode.FullPath)
        (mosaicImage, maskImage) = mosaic.AssembleTiles(ImageDir, usecluster=UseCluster)

        if mosaicImage is None or maskImage is None:
            Logger.error("No output produced assembling " + TransformNode.FullPath)
            return None


        if hasattr(TransformNode, 'CropBox'):
            cmdTemplate = "convert %(Input)s -crop %(width)dx%(height)d%(Xo)+d%(Yo)+d! -background black -flatten %(Output)s"
            (Xo, Yo, Width, Height) = nornir_shared.misc.ListFromAttribute(TransformNode.CropBox)

            # Figure out the downsample level, adjust the crop box, and crop
            Xo = Xo / float(thisLevel)
            Yo = Yo / float(thisLevel)
            Width = Width / float(thisLevel)
            Height = Height / float(thisLevel)

            Logger.warn("Cropping assembled image to volume boundary")

            mosaicImage = core.CropImage(mosaicImage, Xo, Yo, Width, Height)
            maskImage = core.CropImage(maskImage, Xo, Yo, Width, Height)

        imsave(tempOutputFullPath, mosaicImage)
        imsave(tempMaskOutputFullPath, maskImage)

        # Run convert on the output to make sure it is interlaced
        if(Interlace):
            ConvertCmd = 'Convert ' + tempOutputFullPath + ' -quality 106 -interlace PNG ' + tempOutputFullPath
            Logger.warn("Interlacing assembled image")
            subprocess.call(ConvertCmd + " && exit", shell=True)

        shutil.move(tempOutputFullPath, ImageNode.FullPath)
        shutil.move(tempMaskOutputFullPath, MaskImageNode.FullPath)

        # ImageNode.Checksum = nornir_shared.Checksum.FilesizeChecksum(ImageNode.FullPath)
        # MaskImageNode.Checksum = nornir_shared.Checksum.FilesizeChecksum(MaskImageNode.FullPath)

    BuildImagePyramid(FilterNode.Imageset, Logger, **kwargs)
    BuildImagePyramid(MaskFilterNode.Imageset, Logger, **kwargs)

    return FilterNode


def AssembleTransformIrTools(Parameters, Logger, ChannelNode, PyramidNode, TransformNode, ThumbnailSize=256, Interlace=True, **kwargs):
    '''Assemble a transform using the ir-tools
       @ChannelNode - TransformNode lives under ChannelNode
       '''
    Feathering = Parameters.get('Feathering', 'binary')

    FilterNode = PyramidNode.FindParent('Filter')
    MaskFilterNode = FilterNode.GetOrCreateMaskFilter(FilterNode.MaskName)
    # ChannelNode = FilterNode.FindParent('Channel')
    SectionNode = ChannelNode.FindParent('Section')

    NodesToSave = []

    MangledName = misc.GenNameFromDict(Parameters) + TransformNode.Type

    PyramidLevels = SortedListFromDelimited(kwargs.get('Levels', [1, 2, 4, 8, 16, 32, 64, 128, 256]))

    OutputImageNameTemplate = Config.Current.SectionTemplate % SectionNode.Number + "_" + ChannelNode.Name + "_" + FilterNode.Name + ".png"
    OutputImageMaskNameTemplate = Config.Current.SectionTemplate % SectionNode.Number + "_" + ChannelNode.Name + "_" + MaskFilterNode.Name + ".png"

    FilterNode.Imageset.SetTransform(TransformNode)
    MaskFilterNode.Imageset.SetTransform(TransformNode)

    argstring = misc.ArgumentsFromDict(Parameters)
    irassembletemplate = 'ir-assemble ' + argstring + ' -sh 1 -sp %(pixelspacing)i -save %(OutputImageFile)s -load %(InputFile)s -mask %(OutputMaskFile)s -image_dir %(ImageDir)s '

    LevelFormatTemplate = PyramidNode.attrib.get('LevelFormat', Config.Current.LevelFormat)

    thisLevel = PyramidLevels[0]

    # Create a node for this level
    ImageLevelNode = FilterNode.Imageset.GetOrCreateLevel(thisLevel)
    ImageMaskLevelNode = MaskFilterNode.Imageset.GetOrCreateLevel(thisLevel)

    if not os.path.exists(ImageLevelNode.FullPath):
        os.makedirs(ImageLevelNode.FullPath)

    if not os.path.exists(ImageMaskLevelNode.FullPath):
        os.makedirs(ImageMaskLevelNode.FullPath)

    thisLevelPathStr = OutputImageNameTemplate % {'level' : thisLevel,
                                                  'transform' : TransformNode.Name}
    thisLevelMaskPathStr = OutputImageMaskNameTemplate % {'level' : thisLevel,
                                                  'transform' : TransformNode.Name}

    ImageName = Config.Current.SectionTemplate % SectionNode.Number + "_" + kwargs.get('ImageName', 'assemble')

    # Should Replace any child elements
    ImageNode = ImageLevelNode.find('Image')
    if(ImageNode is None):
        ImageNode = VolumeManagerETree.ImageNode(OutputImageNameTemplate)
        ImageLevelNode.append(ImageNode)

    MaskImageNode = ImageMaskLevelNode.find('Image')
    if(MaskImageNode is None):
        MaskImageNode = VolumeManagerETree.ImageNode(OutputImageMaskNameTemplate)
        ImageMaskLevelNode.append(MaskImageNode)

    ImageNode.MaskPath = MaskImageNode.FullPath

    if not (os.path.exists(ImageNode.FullPath) and os.path.exists(MaskImageNode.FullPath)):
        LevelFormatStr = LevelFormatTemplate % thisLevel
        ImageDir = os.path.join(PyramidNode.FullPath, LevelFormatStr)

        tempOutputFullPath = os.path.join(ImageDir, 'Temp.png')
        tempMaskOutputFullPath = os.path.join(ImageDir, 'TempMask.png')

        cmd = irassembletemplate % {'pixelspacing' : thisLevel,
                                    'OutputImageFile' : tempOutputFullPath,
                                    'OutputMaskFile' : tempMaskOutputFullPath,
                                    'InputFile' : TransformNode.FullPath,
                                    'ImageDir' : ImageDir}
        prettyoutput.Log(cmd)
        subprocess.call(cmd + " && exit", shell=True)

        if hasattr(TransformNode, 'CropBox'):
            cmdTemplate = "convert %(Input)s -crop %(width)dx%(height)d%(Xo)+d%(Yo)+d! -background black -flatten %(Output)s"
            (Xo, Yo, Width, Height) = nornir_shared.misc.ListFromAttribute(TransformNode.CropBox)

            # Figure out the downsample level, adjust the crop box, and crop
            Xo = Xo / float(thisLevel)
            Yo = Yo / float(thisLevel)
            Width = Width / float(thisLevel)
            Height = Height / float(thisLevel)

            cmd = cmdTemplate % {'Input' : tempOutputFullPath,
                                 'Output' : tempOutputFullPath,
                                 'Xo' :-Xo,
                                 'Yo' :-Yo,
                                 'width' : Width,
                                 'height' : Height}

            maskcmd = cmdTemplate % {'Input' : tempMaskOutputFullPath,
                                 'Output' : tempMaskOutputFullPath,
                                 'Xo' :-Xo,
                                 'Yo' :-Yo,
                                 'width' : Width,
                                 'height' : Height}

            Logger.warn("Cropping assembled image to volume boundary")
            # subprocess.call(cmd + " && exit", shell=True)
            # subprocess.call(maskcmd + " && exit", shell=True)

        # Run convert on the output to make sure it is interlaced
        if(Interlace):
            ConvertCmd = 'Convert ' + tempOutputFullPath + ' -quality 106 -interlace PNG ' + tempOutputFullPath
            Logger.warn("Interlacing assembled image")
            subprocess.call(ConvertCmd + " && exit", shell=True)

        if os.path.exists(tempOutputFullPath):
            shutil.move(tempOutputFullPath, ImageNode.FullPath)
            shutil.move(tempMaskOutputFullPath, MaskImageNode.FullPath)
        else:
            Logger.error("Assemble produced no output " + ImageNode.FullPath)

        # ImageNode.Checksum = nornir_shared.Checksum.FilesizeChecksum(ImageNode.FullPath)
        # MaskImageNode.Checksum = nornir_shared.Checksum.FilesizeChecksum(MaskImageNode.FullPath)

    BuildImagePyramid(FilterNode.Imageset, Logger, **kwargs)
    BuildImagePyramid(MaskFilterNode.Imageset, Logger, **kwargs)

    return FilterNode


def BuildImagePyramid(ImageSetNode, Logger, Levels=None, Interlace=True, **kwargs):
    '''@ImageSetNode'''
    if Levels is None:
        Levels = [1, 2, 4, 8, 16, 32, 64, 128, 256]

    PyramidLevels = nornir_shared.misc.SortedListFromDelimited(Levels);

    SaveImageSet = False

    # Build downsampled images for every level below the input image level node
    for i in range(1, len(PyramidLevels)):

        # OK, check for a node with the previous downsample level. If it exists use it to build this level if it does not exist
        SourceLevel = PyramidLevels[i - 1]
        SourceImageNode = ImageSetNode.GetImage(SourceLevel)
        if(SourceImageNode is None):
            Logger.error('Source image not found in level' + str(SourceLevel))
            return None

        thisLevel = PyramidLevels[i]
        TargetImageNode = ImageSetNode.GetOrCreateImage(thisLevel, SourceImageNode.Path)
        if not os.path.exists(TargetImageNode.Parent.FullPath):
            os.makedirs(TargetImageNode.Parent.FullPath)

        buildLevel = False
        if os.path.exists(TargetImageNode.FullPath):
            if 'InputImageChecksum' in SourceImageNode.attrib:
                TargetImageNode = transforms.RemoveOnMismatch(TargetImageNode, "InputImageChecksum", SourceImageNode.InputImageChecksum)

                if TargetImageNode is None:
                    buildLevel = True
                    # Recreate the node if needed
                    TargetImageNode = ImageSetNode.GetOrCreateImage(thisLevel)

    #            RemoveOnMismatch()
    #            if(TargetImageNode.attrib["InputImageChecksum"] != SourceImageNode.InputImageChecksum):
    #                os.remove(TargetImageNode.FullPath)
        else:
            buildLevel = True

        if buildLevel:
            scale = thisLevel / SourceLevel
            NewP = images.Shrink(SourceImageNode.FullPath, TargetImageNode.FullPath, scale)
            NewP.wait()

            if 'InputImageChecksum' in SourceImageNode.attrib:
                TargetImageNode.attrib['InputImageChecksum'] = str(SourceImageNode.InputImageChecksum)


            Logger.info('Shrunk ' + TargetImageNode.FullPath)

            if(Interlace):
                ConvertCmd = 'Convert ' + TargetImageNode.FullPath + ' -quality 106 -interlace PNG ' + TargetImageNode.FullPath
                Logger.info('Interlacing start ' + TargetImageNode.FullPath)
                prettyoutput.Log(ConvertCmd)
                subprocess.call(ConvertCmd + " && exit", shell=True)
                SaveImageSet = True

            # TargetImageNode.Checksum = nornir_shared.Checksum.FilesizeChecksum(TargetImageNode.FullPath)

    if SaveImageSet:
        return ImageSetNode

    return None




def __LoadAssembleTilesXML(XmlFilePath, Logger=None):

    class TilesetInfo:
        pass

    Info = TilesetInfo()

    try:
        dom = xml.dom.minidom.parse(XmlFilePath)
        levels = dom.getElementsByTagName("Level")
        level = levels[0]

        Info.GridDimX = int(level.getAttribute('GridDimX'))
        Info.GridDimY = int(level.getAttribute('GridDimY'))
        Info.TileXDim = int(level.getAttribute('TileXDim'))
        Info.TileYDim = int(level.getAttribute('TileYDim'))
        Info.FilePrefix = level.getAttribute('FilePrefix')
        Info.FilePostfix = level.getAttribute('FilePostfix')
        Info.Downsample = float(level.getAttribute('Downsample'))
    except Exception as e:
        Logger.warning("Failed to parse XML File: " + XmlFilePath)
        Logger.warning(str(e))
        return

    return Info


def AssembleTileset(Parameters, FilterNode, PyramidNode, TransformNode, TileSetName=None, TileWidth=256, TileHeight=256, Logger=None, **kwargs):
    '''Create full resolution tiles of specfied size for the mosaics
       @FilterNode
       @TransformNode'''
    prettyoutput.CurseString('Stage', "Assemble Tile Pyramids")

    Feathering = Parameters.get('Feathering', 'binary')

    InputTransformNode = TransformNode
    FilterNode = PyramidNode.FindParent('Filter')

    if(TileSetName is None):
        TileSetName = 'Tileset'

    InputLevelNode = PyramidNode.GetChildByAttrib('Level', 'Downsample', 1)
    if InputLevelNode is None:
        Logger.warning("No input tiles found for assembletiles")
        return

    MangledName = misc.GenNameFromDict(Parameters) + InputTransformNode.Type
    CmdCount = 0

    TileSetNode = VolumeManagerETree.TilesetNode()
    [added, TileSetNode] = FilterNode.UpdateOrAddChildByAttrib(TileSetNode)

    TileSetNode.TileXDim = str(TileWidth)
    TileSetNode.TileYDim = str(TileHeight)
    TileSetNode.FilePostfix = '.png'
    TileSetNode.FilePrefix = FilterNode.Name + '_'
    TileSetNode.CoordFormat = Config.Current.GridTileCoordFormat

    if not os.path.exists(TileSetNode.FullPath):
        Logger.info("Creating Directory: " + TileSetNode.FullPath)
        os.makedirs(TileSetNode.FullPath)

    # OK, check if the first level of the tileset exists
    LevelOne = TileSetNode.GetChildByAttrib('Level', 'Downsample', 1)
    if(LevelOne is None):

        MFile = mosaicfile.MosaicFile.Load(InputTransformNode.FullPath)

        # Need to call ir-assemble
        LevelOne = VolumeManagerETree.LevelNode(Level=1)
        [added, LevelOne] = TileSetNode.UpdateOrAddChildByAttrib(LevelOne, 'Downsample')

        if not os.path.exists(LevelOne.FullPath):
            os.makedirs(LevelOne.FullPath)

        # The output file name is used as a prefix for the tiles written
        OutputPath = os.path.join(LevelOne.FullPath, FilterNode.Name + '.png')
        OutputXML = os.path.join(LevelOne.FullPath, FilterNode.Name + '.xml')

        assembleTemplate = 'ir-assemble -load %(transform)s -save %(LevelPath)s -image_dir %(ImageDir)s -feathering %(feathering)s -load_as_needed -tilesize %(width)d %(height)d -sp 1'
        cmd = assembleTemplate % {'transform' : InputTransformNode.FullPath,
                                  'LevelPath' : OutputPath,
                                  'ImageDir' : InputLevelNode.FullPath,
                                  'feathering' : Feathering,
                                  'width' : TileWidth,
                                  'height' : TileHeight}

        if not os.path.exists(OutputXML):
            Logger.info(cmd)
            prettyoutput.Log(cmd)
            subprocess.call(cmd + " && exit", shell=True)

            # Figure out the grid tile format

        else:
            Logger.info("Assemble tiles output already exists")


        if not os.path.exists(OutputXML):
            # Something went wrong, do not save
            return None

        Info = __LoadAssembleTilesXML(XmlFilePath=OutputXML, Logger=Logger)
        LevelOne.GridDimX = str(Info.GridDimX)
        LevelOne.GridDimY = str(Info.GridDimY)

    return FilterNode


# OK, now build/check the remaining levels of the tile pyramids
def BuildTilesetPyramid(TileSetNode, Pool=None, **kwargs):
    '''@TileSetNode'''
    if Pool is None:
        Pool = Pools.GetGlobalClusterPool()
    FilterNode = TileSetNode.FindParent('Filter')

    MaxLevelNode = None
    for i  in range(0, len(TileSetNode.Levels)):
        L = TileSetNode.Levels[i]
        if MaxLevelNode is None:
            MaxLevelNode = L
        elif L.Downsample > MaxLevelNode.Downsample:
            MaxLevelNode = L

    # LevelNode = TileSetNode.Levels[len(TileSetNode.Levels)-1]
    LevelNode = MaxLevelNode

    # If the tileset is already a single tile, then do not downsample
    if(LevelNode.GridDimX == 1 and LevelNode.GridDimY == 1):
        return LevelNode.Downsample

    ShrinkFactor = 0.5

    newXDim = float(LevelNode.GridDimX) * ShrinkFactor
    newYDim = float(LevelNode.GridDimY) * ShrinkFactor

    newXDim = int(math.ceil(newXDim))
    newYDim = int(math.ceil(newYDim))

    FilePrefix = TileSetNode.FilePrefix
    FilePostfix = TileSetNode.FilePostfix

    # If there is only one tile in the next level, try to find a thumbnail image an change the downsample level
    if(newXDim == 1 and newYDim == 1):
        return

    # Need to call ir-assemble
    NextLevelNode = VolumeManagerETree.LevelNode(LevelNode.Downsample * 2)
    [added, NextLevelNode] = TileSetNode.UpdateOrAddChildByAttrib(NextLevelNode, 'Downsample')

    NextLevelNode.GridDimX = str(newXDim)
    NextLevelNode.GridDimY = str(newYDim)

    # Check to make sure the level hasn't already been generated and we've just missed the
    [Valid, Reason] = NextLevelNode.IsValid()
    if not Valid:

        # XMLOutput = os.path.join(NextLevelNode, os.path.basename(XmlFilePath))

        try:
            os.makedirs(NextLevelNode.FullPath)
        except:
            e = 1  # Just a garbage statement, not sure how to swallow an exception

        # Merge all the tiles we can find into tiles of the same size
        for iY in range(0, newYDim):

            '''We wait for the last task we queued for each row so we do not swamp the ProcessPool but are not waiting for the entire pool to empty'''
            FirstTaskForRow = None

            for iX in range(0, newXDim):

                X1 = iX * 2
                X2 = X1 + 1
                Y1 = iY * 2
                Y2 = Y1 + 1

                # OutputFile = FilePrefix + 'X' + Config.GridTileCoordFormat % iX + '_Y' + Config.GridTileCoordFormat % iY + FilePostfix
                OutputFile = Config.Current.GridTileNameTemplate % {'prefix' : FilePrefix,
                                                     'X' : iX,
                                                     'Y' : iY,
                                                     'postfix' : FilePostfix }

                OutputFileFullPath = os.path.join(NextLevelNode.FullPath, OutputFile)

                # Skip if file already exists
                # if(os.path.exists(OutputFileFullPath)):
                #    continue

                # TopLeft = FilePrefix + 'X' + Config.GridTileCoordFormat % X1 + '_Y' + Config.GridTileCoordFormat % Y1 + FilePostfix
                # TopRight = FilePrefix + 'X' + Config.GridTileCoordFormat % X2 + '_Y' + Config.GridTileCoordFormat % Y1 + FilePostfix
                # BottomLeft = FilePrefix + 'X' + Config.GridTileCoordFormat % X1 + '_Y' + Config.GridTileCoordFormat % Y2 + FilePostfix
                # BottomRight = FilePrefix + 'X' + Config.GridTileCoordFormat % X2 + '_Y' + Config.GridTileCoordFormat % Y2 + FilePostfix
                TopLeft = Config.Current.GridTileNameTemplate % {'prefix' : FilePrefix,
                                                     'X' : X1,
                                                     'Y' : Y1,
                                                     'postfix' : FilePostfix }
                TopRight = Config.Current.GridTileNameTemplate % {'prefix' : FilePrefix,
                                                     'X' : X2,
                                                     'Y' : Y1,
                                                     'postfix' : FilePostfix }
                BottomLeft = Config.Current.GridTileNameTemplate % {'prefix' : FilePrefix,
                                                     'X' : X1,
                                                     'Y' : Y2,
                                                     'postfix' : FilePostfix }
                BottomRight = Config.Current.GridTileNameTemplate % {'prefix' : FilePrefix,
                                                     'X' : X2,
                                                     'Y' : Y2,
                                                     'postfix' : FilePostfix }


                TopLeft = os.path.join(LevelNode.FullPath, TopLeft)
                TopRight = os.path.join(LevelNode.FullPath, TopRight)
                BottomLeft = os.path.join(LevelNode.FullPath, BottomLeft)
                BottomRight = os.path.join(LevelNode.FullPath, BottomRight)

                nullCount = 0

                if(os.path.exists(TopLeft) == False):
                    TopLeft = 'null:'
                    nullCount = nullCount + 1
                if(os.path.exists(TopRight) == False):
                    TopRight = 'null:'
                    nullCount = nullCount + 1
                if(os.path.exists(BottomLeft) == False):
                    BottomLeft = 'null:'
                    nullCount = nullCount + 1
                if(os.path.exists(BottomRight) == False):
                    BottomRight = 'null:'
                    nullCount = nullCount + 1

                if(nullCount == 4):
                    continue

                # Complicated ImageMagick call reads in up to four adjacent tiles, merges them, and shrinks
                # BUG this assumes we only downsample by a factor of two
                cmd = ("montage " + TopLeft + ' ' + TopRight + ' ' +
                      BottomLeft + ' ' + BottomRight +
                      ' -geometry ' + str(TileSetNode.TileXDim / 2) + 'x' + str(TileSetNode.TileYDim / 2)
                      + ' -set colorspace RGB  -mode Concatenate -tile 2x2 -background black '
                      + ' -depth 8 -type Grayscale -define png:format=png8 ' + OutputFileFullPath)
                # prettyoutput.CurseString('Cmd', cmd)
                # prettyoutput.Log(
                # TestOutputFileFullPath = os.path.join(NextLevelNode.FullPath, 'Test_' + OutputFile)

                montageBugFixCmd = 'convert ' + OutputFileFullPath + ' -set colorspace RGB -type Grayscale ' + OutputFileFullPath

                task = Pool.add_process(cmd, cmd + " && " + montageBugFixCmd + " && exit", shell=True)

                if FirstTaskForRow is None:
                    FirstTaskForRow = task


            # TaskString = "Building tiles for downsample %g" % NextLevelNode.Downsample
            # prettyoutput.CurseProgress(TaskString, iY + 1, newYDim)

            # We can easily saturate the pool with hundreds of thousands of tasks.
            # If the pool has a reasonable number of tasks then we should wait for
            # a task from a row to complete before queueing more.
            if hasattr(Pool, 'tasks'):
                if Pool.tasks.qsize() > 256:
                    FirstTaskForRow.wait()
                    FirstTaskForRow = None
            elif hasattr(Pool, 'ActiveTasks'):
                if Pool.ActiveTasks > 512:
                    FirstTaskForRow.wait()
                    FirstTaskForRow = None

            prettyoutput.Log("\nBeginning Row " + str(iY + 1) + " of " + str(newYDim))

        Pool.wait_completion()

    else:
        logging.info("Level was already generated " + str(TileSetNode))

    # This was a lot of work, make sure it is saved before queueing the next level
    TileSetNode.Save()
    prettyoutput.Log("\nTileset level completed")

    return BuildTilesetPyramid(TileSetNode, Pool=Pool, **kwargs)

if __name__ == "__main__":

    TestImageDir = 'D:/BuildScript/Test/Images'
    Pool = Pools.GetGlobalProcessPool()

    BadTestImage = os.path.join(TestImageDir, 'Bad101.png')
    BadTestImageOut = os.path.join(TestImageDir, 'Bad101Shrink.png')

    task = Shrink(Pool, BadTestImage, BadTestImageOut, 0.5)
    print 'Bad image return value: ' + str(task.returncode)
    Pool.wait_completion()

    GoodTestImage = os.path.join(TestImageDir, '400.png')
    GoodTestImageOut = os.path.join(TestImageDir, '400Shrink.png')

    task = Shrink(Pool, GoodTestImage, GoodTestImageOut, 0.5)
    Pool.wait_completion()
    print 'Good image return value: ' + str(task.returncode)