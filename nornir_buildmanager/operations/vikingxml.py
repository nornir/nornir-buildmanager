'''
Created on Jul 3, 2012

@author: Jamesan
'''

import copy
import functools
import os

import nornir_buildmanager.VolumeManagerETree
from nornir_imageregistration.files import *
from nornir_shared.files import RecurseSubdirectories
import nornir_shared.prettyoutput as prettyoutput
import xml.etree.ElementTree as ETree

ECLIPSE = 'ECLIPSE' in os.environ

def CreateXMLIndex(path, server=None):

    VolumeXMLDirs = RecurseSubdirectories(Path=path, RequiredFiles='Volume.xml')

    for directory in VolumeXMLDirs:

        InputVolumeNode = nornir_buildmanager.VolumeManagerETree.VolumeManager.Load(directory, Create=False)
        if not InputVolumeNode is None:
            CreateVikingXML(VolumeNode=InputVolumeNode)

def CreateVikingXML(StosMapName=None, StosGroupName=None, OutputFile=None, Host=None, **kwargs):
    '''When passed a volume node, creates a VikingXML file'''
    InputVolumeNode = kwargs.get('VolumeNode')
    path = InputVolumeNode.Path

    if OutputFile is None:
        OutputFile = "Volume.VikingXML"

    if not OutputFile.lower().endswith('.vikingxml'):
        OutputFile = OutputFile + ".VikingXML"

    # Create our XML File
    OutputXMLFilename = os.path.join(path, OutputFile)

    # Load the inputXML file and begin parsing

    # Create the root output node
    OutputVolumeNode = ETree.Element('Volume', {'Name' : InputVolumeNode.Name,
                                                'num_stos' : '0',
                                                'num_sections' : '0',
                                                'InputChecksum' : InputVolumeNode.Checksum})

    (units_of_measure, units_per_pixel) = DetermineVolumeScale(InputVolumeNode)
    if units_of_measure is not None:
        AddScaleData(OutputVolumeNode, units_of_measure, units_per_pixel)

    ParseSections(InputVolumeNode, OutputVolumeNode)

    RemoveDuplicateScaleEntries(OutputVolumeNode, units_of_measure, units_per_pixel)

    ParseStos(InputVolumeNode, OutputVolumeNode, StosMapName, StosGroupName)

    OutputXML = ETree.tostring(OutputVolumeNode).decode('utf-8')
    # prettyoutput.Log(OutputXML)

    hFile = open(OutputXMLFilename, 'w')
    hFile.write(OutputXML)
    hFile.close()

    # Walk down to the path from the root directory, merging about.xml's as we go
    Url = RecursiveMergeAboutXML(path, OutputXMLFilename)

    if not Host is None and len(Host) > 0:
        OutputVolumeNode.attrib['host'] = Host

    prettyoutput.Log("Launch string:")
    prettyoutput.Log(Url)
    finalUrl = url_join(Url, OutputFile)
    vikingUrl = "http://connectomes.utah.edu/Software/Viking4/viking.application?" + finalUrl

    prettyoutput.Log(vikingUrl)
    return


def RecursiveMergeAboutXML(path, xmlFileName, sourceXML="About.xml"):

    if(path is None or  len(path) == 0):
        return

    [Parent, tail] = os.path.split(path)

    if(tail is None or len(tail) == 0):
        return

    Url = RecursiveMergeAboutXML(Parent, xmlFileName, sourceXML)

    NewUrl = MergeAboutXML(xmlFileName, os.path.join(path, "About.xml"))
    if NewUrl is not None:
        if len(NewUrl) > 0:
            Url = NewUrl

    return Url

def DetermineVolumeScale(InputVolumeNode):
    '''
    Returns the highest resolution found in all sections of the volume
    '''

    ScaleNodes = list(InputVolumeNode.findall('Block/Section/Channel/Scale'))
    if ScaleNodes is None or len(ScaleNodes) == 0:
        return (None, None)

    #This code assumes all units are the same
    units_of_measure = map(lambda s: s.X.UnitsOfMeasure, ScaleNodes )

    units_all_equal = all(x == units_of_measure[0] for x in units_of_measure)
    if not units_all_equal:
        raise AssertionError("Not all units are equal in the volume.  This can be supported, but is not added yet.")

    UnitsPerPixel = map(lambda s: s.X.UnitsPerPixel, ScaleNodes )

    min_UnitsPerPixel = min(UnitsPerPixel)

    return (units_of_measure[0], min_UnitsPerPixel)


def AddScaleData(OutputNode, units_of_measure, units_per_pixel):
    '''Adds a scale node to the OutputNode'''

    OutputScaleNode = ETree.SubElement(OutputNode, 'Scale', {'UnitsOfMeasure' : str(units_of_measure),
                                                           'UnitsPerPixel' : str(units_per_pixel)})

    return OutputScaleNode


def AddChannelScale(InputChannelNode, OutputNode):
    '''
    Add scale element to node based on the channel's scale information
    '''

    ScaleNode = InputChannelNode.GetScale()
    if ScaleNode is None:
        return

    AddScaleData(OutputNode, ScaleNode.X.UnitsOfMeasure, ScaleNode.X.UnitsPerPixel)


def RemoveDuplicateScaleEntries(OutputNode, volume_units_of_measure, volume_units_per_pixel):
    '''Remove scale elements that match the volume's default scale'''

    for subelem in OutputNode:
        scale_node = subelem.find('Scale')
        if scale_node is None:
            RemoveDuplicateScaleEntries(subelem, volume_units_of_measure, volume_units_per_pixel)
        else:
            #Determine if the scales match
            elem_units_of_measure = scale_node.attrib['UnitsOfMeasure']
            elem_units_per_pixel = float(scale_node.attrib['UnitsPerPixel'])

            if elem_units_of_measure == volume_units_of_measure and volume_units_per_pixel == elem_units_per_pixel:
                subelem.remove(scale_node)

            continue


def ParseStos(InputVolumeNode, OutputVolumeNode, StosMapName, StosGroupName):

    global ECLIPSE

    lastCreated = None
    bestGroup = None

    if StosMapName is None:
        print "No StosMapName specified, not adding stos"
        return
    if StosGroupName is None:
        print "No StosGroupName specified, not adding stos"
        return

    num_stos = 0
    print("Adding Slice-to-slice transforms\n")
    UpdateTemplate = "%(mapped)d -> %(control)d"
    for BlockNode in InputVolumeNode.findall('Block'):
        StosMapNode = BlockNode.GetChildByAttrib("StosMap", 'Name', StosMapName)
        if StosMapNode is None:
            continue

        StosGroup = BlockNode.GetChildByAttrib("StosGroup", "Name", StosGroupName)
        if StosGroup is None:
            print "StosGroup %s not found.  No slice-to-slice transforms are being included" % StosGroupName
            continue

        for Mapping in StosMapNode.findall('Mapping'):

            for MappedSection in Mapping.Mapped:
                MappingString = UpdateTemplate % {'mapped' : int(MappedSection),
                                                              'control' : int(Mapping.Control)}

                SectionMappingNode = StosGroup.GetChildByAttrib('SectionMappings', 'MappedSectionNumber', MappedSection)
                if SectionMappingNode is None:
                    print "No Section Mapping found for " + MappingString
                    continue

                transform = SectionMappingNode.GetChildByAttrib('Transform', 'ControlSectionNumber', Mapping.Control)
                if transform is None:
                    print "No Section Mapping Transform found for " + MappingString
                    continue

                OutputStosNode = ETree.SubElement(OutputVolumeNode, 'stos', {'GroupName' : StosGroup.Name,
                                                                      'controlSection' : str(transform.ControlSectionNumber),
                                                                      'mappedSection' :  str(transform.MappedSectionNumber),
                                                                      'path' : os.path.join(BlockNode.Path, StosGroup.Path, transform.Path),
                                                                      'pixelspacing' : '%g' % StosGroup.Downsample,
                                                                      'type' : transform.Type })

                UpdateString = UpdateTemplate % {'mapped' : int(transform.MappedSectionNumber),
                                                              'control' : int(transform.ControlSectionNumber)}



                if not ECLIPSE:
                    print('\b' * 80)

                print(UpdateString)

                num_stos = num_stos + 1

    OutputVolumeNode.attrib["num_stos"] = '%g' % num_stos


def ParseSections(InputVolumeNode, OutputVolumeNode):

    # Find all of the section tags
    print("Adding Sections\n")
    for BlockNode in InputVolumeNode.findall('Block'):
        for SectionNode in BlockNode.Sections:

            if not ECLIPSE:
                print('\b' * 8)

            print('%g' % SectionNode.Number)

            # Create a section node, or create on if it doesn't exist
            OutputSectionNode = OutputVolumeNode.find("Section[@Number='%d']" % SectionNode.Number)
            if(OutputSectionNode is None):
                OutputSectionNode = ETree.SubElement(OutputVolumeNode, 'Section', {'Number' : str(SectionNode.Number),
                                                         'Path' : os.path.join(BlockNode.Path, SectionNode.Path),
                                                         'Name' : SectionNode.Name})

            ParseChannels(SectionNode, OutputSectionNode)

            NotesNodes = SectionNode.findall('Notes')
            for NoteNode in NotesNodes:
                # Copy over Notes elements verbatim
                OutputSectionNode.append(copy.deepcopy(NoteNode))

    AllSectionNodes = OutputVolumeNode.findall('Section')
    OutputVolumeNode.attrib['num_sections'] = str(len(AllSectionNodes))

def ParseChannels(SectionNode, OutputSectionNode):

    for ChannelNode in SectionNode.Channels:
        ScaleNode = ChannelNode.find('Scale')

        for TransformNode in ChannelNode.findall('Transform'):
            OutputTransformNode = ParseTransform(TransformNode, OutputSectionNode)
            if not OutputTransformNode is None:
                OutputTransformNode.attrib['Path'] = os.path.join(ChannelNode.Path, OutputTransformNode.attrib['Path'])

        for FilterNode in ChannelNode.Filters:
            for tilepyramid in FilterNode.findall('TilePyramid'):
                OutputPyramidNode = ParsePyramidNode(FilterNode, tilepyramid, OutputSectionNode)
                OutputPyramidNode.attrib['Path'] = os.path.join(ChannelNode.Path, FilterNode.Path, OutputPyramidNode.attrib['Path'])
                if ScaleNode is not None:
                    AddScaleData(OutputPyramidNode, ScaleNode.X.UnitsOfMeasure, ScaleNode.X.UnitsPerPixel)
            for tileset in FilterNode.findall('Tileset'):
                OutputTilesetNode = ParseTilesetNode(FilterNode, tileset, OutputSectionNode)
                OutputTilesetNode.attrib['path'] = os.path.join(ChannelNode.Path, FilterNode.Path, OutputTilesetNode.attrib['path'])
                if ScaleNode is not None:
                    AddScaleData(OutputTilesetNode, ScaleNode.X.UnitsOfMeasure, ScaleNode.X.UnitsPerPixel)
                print "Tileset found for section " + str(SectionNode.attrib["Number"])    

        NotesNodes = ChannelNode.findall('Notes')
        for NoteNode in NotesNodes:
            # Copy over Notes elements verbatim
            OutputNotesNode = ETree.SubElement(OutputSectionNode, 'Notes')
            OutputNotesNode.text = NoteNode.text
            OutputSectionNode.append(OutputNotesNode)


def ParseTransform(TransformNode, OutputSectionNode):

    mFile = mosaicfile.MosaicFile.Load(TransformNode.FullPath)

    if(mFile is None):
        prettyoutput.LogErr("Unable to load transform: " + TransformNode.FullPath)
        return

    if(mFile.NumberOfImages < 1):
        prettyoutput.LogErr("Not including empty .mosaic file")
        return

    # Figure out what the tile prefix and postfix are for this mosaic file by extrapolating from the first tile filename
    for k in mFile.ImageToTransformString.keys():
        TileFileName = k
        break

    # TileFileName = mFile.ImageToTransformString.keys()[0]

    # Figure out prefix and postfix parts of filenames
    parts = TileFileName.split('.')

    Postfix = parts[len(parts) - 1]

    # Two conventions are commonly used Section#.Tile#.png or Tile#.png
    if(len(parts) == 3):
        Prefix = parts[0]
    else:
        Prefix = ''

    UseForVolume = 'false'
    if('grid' in TransformNode.Name.lower()):
        UseForVolume = 'true'


    #Viking needs the transform names to be consistent, and if transforms are built with different spacings, for TEM and CMP, Viking can't display
    #So we simplify the transform name
    TransformName = TransformNode.Name

    return ETree.SubElement(OutputSectionNode, 'Transform', {'FilePostfix' : Postfix,
                                                          'FilePrefix' : Prefix,
                                                         'Path' : TransformNode.Path,
                                                         'Name' : TransformName,
                                                         'UseForVolume' : UseForVolume})

def ParsePyramidNode(FilterNode, InputPyramidNode, OutputSectionNode):
    OutputPyramidNode = ETree.SubElement(OutputSectionNode, 'Pyramid', {
                                                         'Path' : InputPyramidNode.Path,
                                                         'Name' : FilterNode.Parent.Name + "." + FilterNode.Name + ".Pyramid",
                                                         'LevelFormat' : InputPyramidNode.LevelFormat})

    for LevelNode in InputPyramidNode.Levels:
        ETree.SubElement(OutputPyramidNode, 'Level', {'Path' : LevelNode.Path,
                                                      'Downsample' : '%g' % LevelNode.Downsample})

    return OutputPyramidNode

def ParseTilesetNode(FilterNode, InputTilesetNode, OutputSectionNode):
    OutputTilesetNode = ETree.SubElement(OutputSectionNode, 'Tileset', {
                                                         'path' : InputTilesetNode.Path,
                                                         'name' : FilterNode.Parent.Name + "." + FilterNode.Name,
                                                         'TileXDim' : str(InputTilesetNode.TileXDim),
                                                         'TileYDim' : str(InputTilesetNode.TileYDim),
                                                         'FilePrefix' : InputTilesetNode.FilePrefix,
                                                         'FilePostfix' : InputTilesetNode.FilePostfix,
                                                         'CoordFormat' : InputTilesetNode.CoordFormat})

    for LevelNode in InputTilesetNode.Levels:
        ETree.SubElement(OutputTilesetNode, 'Level', {'path' : LevelNode.Path,
                                                      'Downsample' : '%g' % LevelNode.Downsample,
                                                      'GridDimX' : str(LevelNode.GridDimX),
                                                      'GridDimY' : str(LevelNode.GridDimY)})

    return OutputTilesetNode


# Merge the created VolumeXML with the general definitions in about.XML
def MergeAboutXML(volumeXML, aboutXML):

    import xml.dom.minidom

    prettyoutput.Log('MergeAboutXML ' + str(volumeXML) + ' ' + str(aboutXML))
    if(os.path.exists(volumeXML) == False):
        return
    if(os.path.exists(aboutXML) == False):
        return

    aboutDom = xml.dom.minidom.parse(aboutXML)
    volumeDom = xml.dom.minidom.parse(volumeXML)

    # Figure out which elements are contained in the about dom which need to be injected into the volumeXML
    # If element names match, attributes are added which are missing from the volumeXML.
    # If element names do not match, they are injected into the volumeXML at the appropriate level

    aboutNode = aboutDom.documentElement
    volumeNode = volumeDom.documentElement

    Url = None
    # Volume path is a special case so we append the path to the host name
    if(volumeNode.nodeName == "Volume" and aboutNode.nodeName == "Volume"):
        baseVolumeDir = os.path.dirname(volumeXML)
        baseAboutDir = os.path.dirname(aboutXML)
        relPath = baseVolumeDir.replace(baseAboutDir, '')
        prettyoutput.Log("Relative path: " + relPath)
        Url = UpdateVolumePath(volumeNode, aboutNode, relPath)

    MergeElements(volumeNode, aboutNode)

    prettyoutput.Log("")

    xmlFile = open(volumeXML, "w")
    xmlFile.write(volumeDom.toxml())
    xmlFile.close()

    return Url


def MergeElements(volumeNode, aboutNode):

    if(ElementsEqual(volumeNode, aboutNode)):
        CopyNewAttributes(volumeNode, aboutNode)
        MergeChildren(volumeNode, aboutNode)


# Both arguments should be matching elements
def MergeChildren(volumeParent, aboutParent):

    aboutElement = aboutParent.firstChild
    while(aboutElement is not None):
        if(aboutElement.nodeName is None):
            break

        volumeElements = volumeParent.getElementsByTagName(aboutElement.nodeName)
        # The volume doesn't have any elements like this.  Add them
        if(volumeElements.length == 0):
            newNode = aboutElement.cloneNode(True)
            prettyoutput.Log('NewNode' + newNode.toxml())
            volumeParent.insertBefore(newNode, volumeParent.firstChild)
        else:
            for volElement in volumeElements:
                MergeElements(volElement, aboutElement)

        aboutElement = aboutElement.nextSibling

# Compare the attributes of two elements and return true if they match
def ElementsEqual(volumeElement, aboutElement):
    '''Return true if the elements have the same tag, and the attributes found in both elements have same value'''

    if(aboutElement.nodeName != volumeElement.nodeName):
        return False

    for attrib_key in aboutElement.attributes.keys():
        if not (volumeElement.hasAttribute(attrib_key) and aboutElement.hasAttribute(attrib_key)):
            continue
        if not volumeElement.getAttribute(attrib_key) == aboutElement.getAttribute(attrib_key):
            return False

    return True


    # Volume is the root element so it is always a match
    if(aboutElement.nodeName == "Volume"):
        return True

    # Nodes only match if their attributes match
    if(aboutElement.nodeName == "Section"):
        aboutNumber = aboutElement.getAttribute("number")
        volNumber = volumeElement.getAttribute("number")
        if(aboutNumber != volNumber):
            return False
        else:
            prettyoutput.Log("Equal:")
            prettyoutput.Log('v: ' + volumeElement.nodeName + ' ' + str(volNumber))
            prettyoutput.Log('a: ' + aboutElement.nodeName + ' ' + str(aboutNumber))
            prettyoutput.Log('')

            return True

    return False

def CopyNewAttributes(volumeElement, aboutElement):
    '''Copy the attributes from the aboutElement to the volumeElement'''
#   print 'v: ' + volumeElement.toxml()
#   print 'a: ' + aboutElement.toxml()

    if(aboutElement.hasAttributes() == False):
        return

    attributeMap = aboutElement.attributes
    for i in range(0, attributeMap.length):
        attribute = attributeMap.item(i)

        if(volumeElement.hasAttribute(attribute.name) == False):
            volumeElement.setAttribute(attribute.name, attribute.value)


def UpdateVolumePath(volumeElement, aboutElement, relPath):
    '''
    Special case for updating the root element Volume path
    '''
    if(aboutElement.hasAttributes() == False):
        return

    if(len(relPath) > 0):
        relPath = relPath.lstrip('\\')
        relPath = relPath.lstrip('/')

    attributeMap = aboutElement.attributes
    for i in range(0, attributeMap.length):
        attribute = attributeMap.item(i)

        if(attribute.name == "host"):
            PathURL = url_join(attribute.value, relPath)
            volumeElement.setAttribute("path", PathURL)
            return PathURL

def url_join(*args):
    """Join any arbitrary strings into a forward-slash delimited list.
    Do not strip leading / from first element, nor trailing / from last element."""
    if len(args) == 0:
        return ""

    if len(args) == 1:
        return str(args[0])

    else:
        args = [str(arg).replace("\\", "/") for arg in args]

        work = [args[0]]
        for arg in args[1:]:
            if arg.startswith("/"):
                work.append(arg[1:])
            else:
                work.append(arg)

        joined = functools.reduce(os.path.join, work)

    return joined.replace("\\", "/")


if __name__ == '__main__':
    CreateXMLIndex('D:/Data/RC2_Mini_Pipeline')

    pass
