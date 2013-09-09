'''
Created on Apr 15, 2013

@author: u0490822
'''

import nornir_buildmanager.VolumeManagerETree as VolumeManagerETree
import os
import nornir_shared.misc as misc


def CreateImageNodeHelper(ParentNode, OutputImageName):
    # Create a node in the XML records
    OverlayImageNode = ParentNode.GetChildByAttrib('Image', 'Path', os.path.basename(OutputImageName))
    if not OverlayImageNode is None:
        cleaned = OverlayImageNode.CleanIfInvalid()
        if cleaned:
            OverlayImageNode = None

    if OverlayImageNode is None:
        OverlayImageNode = VolumeManagerETree.ImageNode(os.path.basename(OutputImageName))
        ParentNode.append(OverlayImageNode)

    return OverlayImageNode

def CreateLevelNodes(ParentNode, DownsampleLevels):
    DownsampleLevels = misc.SortedListFromDelimited(DownsampleLevels)

    LevelsCreated = []
    for level in DownsampleLevels:
        LevelNode = ParentNode.GetChildByAttrib('Level', 'Downsample', level)
        if LevelNode is None:
            LevelNode = VolumeManagerETree.LevelNode(level)
            [added, LevelNode] = ParentNode.UpdateOrAddChildByAttrib(LevelNode, 'Downsample')
            LevelsCreated.append(LevelNode)

        if not os.path.exists(LevelNode.FullPath):
            os.makedirs(LevelNode.FullPath)

    return LevelsCreated


def CreateImageSetForImage(ParentNode, ImageSetName, ImageFullPath, Downsample = 1, **attribs):
    if attribs is None:
        attribs = {}

    Type = ""
    if 'Type' in attribs:
        Type = attribs['Type']
        del attribs['Type']

    ImageSetNode = VolumeManagerETree.ImageSetNode(Type, attrib=attribs);
    [NewImageSetNode, ImageSetNode] = ParentNode.UpdateOrAddChildByAttrib(ImageSetNode, 'Path');

    if not os.path.exists(ImageSetNode.FullPath):
        os.makedirs(ImageSetNode.FullPath)

    CreateLevelNodes(ImageSetNode, Downsample)

    LevelNode = ImageSetNode.GetChildByAttrib('Level', 'Downsample', Downsample)

    imagePath = os.path.basename(ImageFullPath)

    imagenode = VolumeManagerETree.ImageNode(imagePath)
    [nodecreated, imagenode] = LevelNode.UpdateOrAddChildByAttrib(imagenode, 'Path')

    return ImageSetNode


def FindSectionImageSet(BlockNode, SectionNumber, ImageSetName, Downsample):
    '''Find the first image matching the criteria'''
    InputImageSetXPathTemplate = "Section[@Number='%(SectionNumber)s']/Channel/Filter/ImageSet[@Name='%(ImageSetName)s']"
    InputImageXPathTemplate = "Level[@Downsample='%(Downsample)d']/Image"

    ImageSets = list(BlockNode.findall(InputImageSetXPathTemplate % {'SectionNumber' : SectionNumber,
                                                                       'ImageSetName' : ImageSetName}))
    for ImageSet in ImageSets:
        ImageXPath = InputImageXPathTemplate % {'Downsample' : Downsample}
        ImageNode = ImageSet.find(ImageXPath)
        return ImageSet

    return None


def MaskImageNodeForImageSet(ImageSetNode, Downsample):
    '''Return a mask image for an image set/downsample combo'''

    if hasattr(ImageSetNode, 'MaskName'):
        MappedMaskSetNode = ImageSetNode.Parent.GetChildByAttrib('ImageSet', 'Name', ImageSetNode.MaskName)

        if not MappedMaskSetNode is None:
            MaskImageXPathTemplate = "Level[@Downsample='%(Downsample)d']/Image"
            MaskImageXPath = MaskImageXPathTemplate % {'Downsample' : Downsample}
            return MappedMaskSetNode.find(MaskImageXPath)

    return None

if __name__ == '__main__':
    pass