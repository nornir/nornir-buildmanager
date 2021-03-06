
import copy
import datetime
import glob
import logging
import math 
import operator
import os
import pickle
import shutil
import sys
import urllib

import nornir_buildmanager
import nornir_buildmanager.validation.transforms
from nornir_imageregistration.files import *
import nornir_imageregistration.transforms.registrationtree
import nornir_shared.checksum
import nornir_shared.files

import VolumeManagerHelpers as VMH
import nornir_buildmanager.operations.tile as tile
import nornir_buildmanager.operations.versions as versions
import nornir_shared.misc as misc
import nornir_shared.prettyoutput as prettyoutput
import nornir_shared.reflection as reflection
import xml.etree.ElementTree as ElementTree 


# Used for debugging with conditional break's, each node gets a temporary unique ID
nid = 0

__LoadedVolumeXMLDict__ = dict()


def ValidateAttributesAreStrings(Element, logger=None):

    # Make sure each attribute is a string
    for k, v in enumerate(Element.attrib):
        assert isinstance(v, str)
        if not isinstance(v, str):
            if logger is None:
                logger = logging.getLogger(__name__ + '.' + 'ValidateAttributesAreStrings')
            logger.warning("Attribute is not a string")
            Element.attrib[k] = str(v)


def NodePathKey(NodeA):
    '''Sort section nodes by number'''
    return NodeA.tag


def NodeCompare(NodeA, NodeB):
    '''Sort section nodes by number'''

    cmpVal = cmp(NodeA.tag, NodeB.tag)

    if cmpVal == 0:
        cmpVal = cmp(NodeA.attrib.get('Path', ''), NodeB.attrib.get('Path', ''))

    return cmpVal


class VolumeManager():
    def __init__(self, volumeData, filename):
        self.Data = volumeData
        self.XMLFilename = filename
        return

    @classmethod
    def Create(cls, VolumePath):
        VolumeManager.Load(VolumePath, Create=True)


    @classmethod
    def Load(cls, VolumePath, Create=False, UseCache=True):
        '''Load the volume information for the specified directory or create one if it doesn't exist'''
        Filename = os.path.join(VolumePath, "VolumeData.xml")
        if not os.path.exists(Filename):
            prettyoutput.Log("Provided volume description file does not exist: " + Filename)

            OldVolume = os.path.join(VolumePath, "Volume.xml")
            if(os.path.exists(OldVolume)):
                VolumeRoot = ElementTree.parse(OldVolume).getroot()
                # Volumes.CreateFromDOM(XMLTree)
                VolumeRoot.attrib['Path'] = VolumePath
                cls.WrapElement(VolumeRoot)
                VolumeManager.__SetElementParent__(VolumeRoot)
                VolumeRoot.Save()


        SaveNewVolume = False
        if not os.path.exists(Filename):
            if(Create):
                if not os.path.exists(VolumePath):
                    os.makedirs(VolumePath)

                VolumeRoot = ElementTree.Element('Volume', {"Name" : os.path.basename(VolumePath), "Path" : VolumePath})
                SaveNewVolume = True                
                # VM =  VolumeManager(VolumeData, Filename)
                # return VM
            else:
                return None
        else:
            # 5/16/2012 Loading these XML files is really slow, so they are cached.
            # if not __LoadedVolumeXMLDict__.get(Filename, None) is None and UseCache:
            #    XMLTree = __LoadedVolumeXMLDict__[Filename]
            # else:
            XMLTree = ElementTree.parse(Filename)
            # VolumeData = Volumes.CreateFromDOM(XMLTree)
            # __LoadedVolumeXMLDict__[Filename] = XMLTree

            VolumeRoot = XMLTree.getroot()

        VolumeRoot.attrib['Path'] = VolumePath
        VolumeRoot = XContainerElementWrapper.wrap(VolumeRoot)
        VolumeManager.__SetElementParent__(VolumeRoot)
        
        if SaveNewVolume:
            VolumeRoot.Save()

        prettyoutput.Log("Volume Root: " + VolumeRoot.attrib['Path'])
        # VolumeManager.__RemoveElementsWithoutPath__(VolumeRoot)

        return VolumeRoot
        # return cls.__init__(VolumeData, Filename)

    @classmethod
    def WrapElement(cls, e):
        OverrideClassName = e.tag + 'Node'
        OverrideClass = reflection.get_module_class('nornir_buildmanager.VolumeManagerETree', OverrideClassName, LogErrIfNotFound=False)
        if not OverrideClass is None:
            OverrideClass.wrap(e)
        elif not (e.attrib.get("Path", None) is None):
            if os.path.isfile(e.attrib.get("Path")):
                XFileElementWrapper.wrap(e)
            else:
                XContainerElementWrapper.wrap(e)
        else:
            XElementWrapper.wrap(e)


    @classmethod
    def __SetElementParent__(cls, Element, ParentElement=None):
        Element.Parent = ParentElement

        for i in range(len(Element) - 1, -1, -1):
            e = Element[i]
            if e.tag in versions.DeprecatedNodes:
                del Element[i]

        for e in Element:
            if(isinstance(e, ElementTree.Element)):
                # Find out if we have an override class defined
                cls.WrapElement(e)

            VolumeManager.__SetElementParent__(e, Element)

        return
    

    @classmethod
    def __SortNodes__(cls, Element):
        '''Remove all elements that should be found on the file system but are not'''
        Element._children.sort(key=operator.attrgetter('SortKey'))

        for e in Element:
            cls.__SortNodes__(e)

    @classmethod
    def __RemoveEmptyElements__(cls, Element):
        '''Remove all elements that should be found on the file system but are not'''
        for i in range(len(Element) - 1, -1, -1):
            e = Element[i]
            if len(e.keys()) == 0 and len(list(e)) == 0:
                Element.remove(e)
                continue

            cls.__RemoveEmptyElements__(e)

        return


    def __str__(self):
        return self.VolumeData.toxml()

    @classmethod
    def CalcVolumeChecksum(cls, VolumeObj):
        XMLString = ElementTree.tostring(VolumeObj, encoding="utf-8")
        OldChecksum = VolumeObj.get('Checksum', '')
        XMLString = XMLString.replace(OldChecksum, "", 1)
        return nornir_shared.checksum.DataChecksum(XMLString)


    @classmethod
    def SaveSingleFile(cls, VolumeObj, xmlfile_fullpath):
        '''Save the volume to a single XML file'''

        fullpath = os.path.dirname(xmlfile_fullpath)

        if not os.path.exists(fullpath):
            os.makedirs(fullpath)

        # prettyoutput.Log("Saving %s" % xmlfilename)


        # prettyoutput.Log("Saving %s" % XMLFilename)

        OutputXML = ElementTree.tostring(VolumeObj, encoding="utf-8")
        # print OutputXML
        with open(xmlfile_fullpath, 'w') as hFile:
            hFile.write(OutputXML)
            hFile.close()

    @classmethod
    def Save(cls, VolumeObj):
        '''Save the volume to an XML file, putting sub-elements in seperate folders'''

        # We cannot include the volume checksum in the calculation because including it changes the checksum'''
        if hasattr(VolumeObj, 'Save'):
            VolumeObj.Save(tabLevel=None)
        else:
            cls.Save(VolumeObj.Parent)

class XPropertiesElementWrapper(ElementTree.Element):
    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return self.tag

    @property
    def Name(self):
        return self.attrib.get("Name", None)

    @Name.setter
    def Name(self, value):
        self.attrib["Name"] = value

    @property
    def Parent(self):
        return self._Parent

    @Parent.setter
    def Parent(self, Value):
        self.__dict__['_Parent'] = Value
        if '__fullpath' in self.__dict__:
            del self.__dict__['__fullpath']

    
    def __init__(self, tag, attrib=None, **extra):
        '''Wrapper for a properties element'''
        super(XPropertiesElementWrapper, self).__init__(tag=tag, attrib=attrib, **extra)

    @classmethod
    def wrap(cls, dictElement):

        dictElement.__class__ = cls
        return dictElement


    def __getEntry__(self, key):
        prettyoutput.Log(key)
        iterator = self.find('Entry[@Name="' + str(key) + '"]')
        if iterator is None:
            return None

        return iterator


    def __getattr__(self, name):

        '''Called when an attribute lookup has not found the attribute in the usual places (i.e. it is not an instance attribute nor is it found in the class tree for self). name is the attribute name. This method should return the (computed) attribute value or raise an AttributeError exception.

        Note that if the attribute is found through the normal mechanism, __getattr__() is not called. (This is an intentional asymmetry between __getattr__() and __setattr__().) This is done both for efficiency reasons and because otherwise __getattr__() would have no way to access other attributes of the instance. Note that at least for instance variables, you can fake total control by not inserting any values in the instance attribute dictionary (but instead inserting them in another object). See the __getattribute__() method below for a way to actually get total control in new-style classes.'''
        if '_children' in self.__dict__:
            entry = self.__getEntry__(name)
            if(entry is not None):
                valstr = entry.attrib["Value"]
                valstr = str(urllib.unquote_plus(valstr))
                return pickle.loads(valstr)

        raise AttributeError(name)


    def __setattr__(self, name, value):


        '''Called when an attribute assignment is attempted. This is called instead of the normal mechanism (i.e. store the value in the instance dictionary). name is the attribute name, value is the value to be assigned to it.'''
        if(hasattr(self.__class__, name)):
            attribute = getattr(self.__class__, name)
            if(isinstance(attribute, property)):
                attribute.fset(self, value)
                return
            else:
                super(XPropertiesElementWrapper, self).__setattr__(name, value)
                return

        if(name in self.__dict__):
            self.__dict__[name] = value
        elif(name[0] == '_'):
            self.__dict__[name] = value
        else:
            valstr = pickle.dumps(value, 0)
            valstr = urllib.quote_plus(valstr)

            entry = self.__getEntry__(name)
            if entry is None:
                entry = ElementTree.Element("Entry", {'Name':name, 'Value':valstr})
                self.append(entry)
            else:
                entry.attrib['Value'] = valstr

    def __delattr__(self, name):
        '''Like __setattr__() but for attribute deletion instead of assignment. This should only be implemented if del obj.name is meaningful for the object.'''
        if(name in self.__dict__):
            self.__dict__.pop(name)
        else:
            entry = self.find('Entry[@Name="' + str(name) + '"]')
            if not entry is None:
                self.remove(entry)


class XElementWrapper(ElementTree.Element):

    logger = logging.getLogger(__name__ + '.' + 'XElementWrapper')

    def sort(self):
        '''Order child elements'''
        self._children.sort(key=operator.attrgetter('SortKey'))

        for c in self._children:
            if len(c._children) <= 1:
                continue

            if isinstance(c, XElementWrapper):
                c.sort()

    @property
    def CreationTime(self):
        datestr = self.get('CreationDate', datetime.datetime.max)
        return datetime.datetime.strptime(datestr)

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return self.tag

    def __str__(self):
        strList = ElementTree.tostringlist(self)
        outStr = ""
        for s in strList:
            outStr = outStr + " " + s.decode('utf-8')
            if s == '>':
                break

        return outStr

    def _GetAttribFromParent(self, attribName):
        p = self._Parent
        while p is not None:
            if attribName in p.attrib:
                return p.attrib[attribName]

            if hasattr(p, '_Parent'):
                p = p._Parent
            else:
                return None

    @property
    def Checksum(self):
        return self.get('Checksum', "")

    @Checksum.setter
    def Checksum(self, Value):
        if not isinstance(Value, str):
            XElementWrapper.logger.warning('Setting non string value on XElement.Checksum, automatically corrected: ' + str(Value))
        self.attrib['Checksum'] = str(Value)
        return

    @property
    def Version(self):
        return float(self.attrib.get('Version', 1.0))

    @Version.setter
    def Version(self, Value):
        self.attrib['Version'] = str(Value)


    @property
    def Root(self):
        '''The root of the element tree'''
        node = self
        while not node.Parent is None:
            node = node.Parent

        return node


    @property
    def Parent(self):
        return self._Parent

    @Parent.setter
    def Parent(self, Value):
        self.__dict__['_Parent'] = Value
        if '__fullpath' in self.__dict__:
            del self.__dict__['__fullpath']

    @classmethod
    def __GetCreationTimeString__(cls):
        now = datetime.datetime.now()
        now = now.replace(microsecond=0)
        return str(now)

    def __init__(self, tag, attrib=None, **extra):

        global nid
        self.__dict__['id'] = nid
        nid = nid + 1

        if(attrib is None):
            attrib = {}
        else:
            StringAttrib = {}
            for k in attrib.keys():
                if not isinstance(attrib[k], str):
                    XElementWrapper.logger.info('Setting non string value on <' + str(tag) + '>, automatically corrected: ' + k + ' -> ' + str(attrib[k]))
                    StringAttrib[k] = str(attrib[k])
                else:
                    StringAttrib[k] = attrib[k]

            attrib = StringAttrib


        super(XElementWrapper, self).__init__(tag=tag, attrib=attrib, **extra)

        self._Parent = None

        if not self.tag.endswith("_Link"):
            self.attrib['CreationDate'] = XElementWrapper.__GetCreationTimeString__()
            self.Version = versions.GetLatestVersionForNodeType(tag)

    @classmethod
    def RemoveDuplicateElements(cls, tagName):
        '''For nodes that should not be duplicated this function removes all but the last created element'''
        pass


    def IsParent(self, node):
        '''Returns true if the node is a parent'''
        if self.Parent is None:
            return False

        if self.Parent == node:
            return True
        else:
            return self.Parent.IsParent(node)

    def IsValid(self):
        '''This function should be overridden by derrived classes.  It returns true if the file system or other external 
           resources match the state recorded within the element.
           
           Returns Tuple of state and a string with a reason'''

        if not 'Version' in self.attrib:
            if versions.GetLatestVersionForNodeType(self.tag) > 1.0:
                return [False, "Node version outdated"]

        if not versions.IsNodeVersionCompatible(self.tag, self.Version):
            return [False, "Node version outdated"]

        return [True, ""]


    def CleanIfInvalid(self):
        '''Remove the contents of this node if it is out of date, returns true if node was cleaned'''
        Valid = self.IsValid()

        if isinstance(Valid, bool):
            Valid = [Valid, ""]
 
        if not Valid[0]:
            self.Clean(Valid[1])
            return True
        
        return False


    def Clean(self, reason=None):
        '''Remove node from element tree and remove any external resources such as files'''

        DisplayStr = ' --- Cleaning ' + self.ToElementString() + ". "

        '''Remove the contents referred to by this node from the disk'''
        prettyoutput.Log(DisplayStr)
        if not reason is None:
            prettyoutput.Log("  --- " + reason)

        # Make sure we clean child elements if needed
        children = copy.copy(self._children)
        for child in children:
            if isinstance(child, XElementWrapper):
                child.Clean(reason="Parent was removed")

        if not self.Parent is None:
            try:
                self.Parent.remove(self)
            except:
                # Sometimes we have not been added to the parent at this point
                pass

    @classmethod
    def wrap(cls, dictElement):
        '''Change the class of an ElementTree.Element(PropertyElementName) to add our wrapper functions'''
        if(dictElement.__class__ == cls):
            return dictElement

        if(isinstance(dictElement, cls)):
            return dictElement

        dictElement.__class__ = cls

        if not 'CreationDate' in dictElement.attrib:
            cls.logger.info("Populating missing CreationDate attribute " + dictElement.ToElementString())
            dictElement.attrib['CreationDate'] = XElementWrapper.__GetCreationTimeString__()

        if(isinstance(dictElement, XContainerElementWrapper)):
            if(not 'Path' in dictElement.attrib):
                print(dictElement.ToElementString() + " no path attribute but being set as container")
            assert('Path' in dictElement.attrib)

        return dictElement


    def ToElementString(self):
        strList = ElementTree.tostringlist(self)
        outStr = ""
        for s in strList:
            outStr = outStr + " " + s.decode('utf-8')
            if s == '>':
                break

        return outStr


    def __getattr__(self, name):

        '''Called when an attribute lookup has not found the attribute in the usual places (i.e. it is not an instance attribute nor is it found in the class tree for self). name is the attribute name. This method should return the (computed) attribute value or raise an AttributeError exception.

        Note that if the attribute is found through the normal mechanism, __getattr__() is not called. (This is an intentional asymmetry between __getattr__() and __setattr__().) This is done both for efficiency reasons and because otherwise __getattr__() would have no way to access other attributes of the instance. Note that at least for instance variables, you can fake total control by not inserting any values in the instance attribute dictionary (but instead inserting them in another object). See the __getattribute__() method below for a way to actually get total control in new-style classes.'''
        if(name in self.attrib):
            return self.attrib[name]

        if name in self.__dict__:
            return self.__dict__[name]

        superClass = super(XElementWrapper, self)
        if not superClass is None:
            if hasattr(superClass, '__getattr__'):
                return superClass.__getattr__(name)

        raise AttributeError(name)

    def __setattr__(self, name, value):

        '''Called when an attribute assignment is attempted. This is called instead of the normal mechanism (i.e. store the value in the instance dictionary). name is the attribute name, value is the value to be assigned to it.'''
        if(hasattr(self.__class__, name)):
            attribute = getattr(self.__class__, name)
            if isinstance(attribute, property):
                if not attribute.fset is None:
                    attribute.fset(self, value)
                    return
                else:
                    assert (not attribute.fset is None)  # Why are we trying to set a property without a setter?
            else:
                super(XElementWrapper, self).__setattr__(name, value)
                return

        if(name in self.__dict__):
            self.__dict__[name] = value
        elif(name[0] == '_'):
            self.__dict__[name] = value
        elif(self.attrib is not None):
            if not isinstance(value, str):
                XElementWrapper.logger.info('Setting non string value on <' + str(self.tag) + '>, automatically corrected: ' + name + ' -> ' + str(value))

                if isinstance(value, float):
                    self.attrib[name] = '%g' % value
                else:
                    self.attrib[name] = str(value)
            else:
                self.attrib[name] = value


    def __delattr__(self, name):

        '''Like __setattr__() but for attribute deletion instead of assignment. This should only be implemented if del obj.name is meaningful for the object.'''
        if(name in self.__dict__):
            self.__dict__.pop(name)
        elif(name in self.attrib):
            self.attrib.pop(name)


    def CompareAttributes(self, dictAttrib):
        '''Compare the passed dictionary with the attributes on the node, return entries which do not match'''
        mismatched = list()

        for entry, val in dictAttrib.items():
            if hasattr(self, entry):
                if getattr(self, entry) != val:
                    mismatched.append(entry)
            else:
                mismatched.append(entry[0])

        return mismatched


    def RemoveOldChildrenByAttrib(self, ElementName, AttribName, AttribValue):
        '''If multiple children match the criteria, we remove all but the child with the latest creation date'''
        Children = self.GetChildrenByAttrib(ElementName, AttribName, AttribValue)
        if Children is None:
            return

        if len(Children) < 2:
            return

        OldestChild = Children[0]
        for iChild in range(1, len(Children)):
            Child = Children[iChild]
            if not hasattr(Child, 'CreationDate'):
                self.remove(Child)
            else:
                if not hasattr(OldestChild, 'CreationDate'):
                    self.remove(OldestChild)
                    OldestChild = Child
                else:
                    if OldestChild.CreationDate < Child.CreationDate:
                        self.remove(OldestChild)
                        OldestChild = Child
                    else:
                        self.remove(Child)


    def GetChildrenByAttrib(self, ElementName, AttribName, AttribValue):
        XPathStr = "%(ElementName)s[@%(AttribName)s='%(AttribValue)s']" % {'ElementName' : ElementName, 'AttribName' : AttribName, 'AttribValue' : AttribValue}
        Children = self.findall(XPathStr)

        if Children is None:
            return []

        return list(Children)

    def GetChildByAttrib(self, ElementName, AttribName, AttribValue):

        XPathStr = ""
        if isinstance(AttribValue, float):
            XPathStr = "%(ElementName)s[@%(AttribName)s='%(AttribValue)g']" % {'ElementName' : ElementName, 'AttribName' : AttribName, 'AttribValue' : AttribValue}
        else:
            XPathStr = "%(ElementName)s[@%(AttribName)s='%(AttribValue)s']" % {'ElementName' : ElementName, 'AttribName' : AttribName, 'AttribValue' : AttribValue}

        assert(len(XPathStr) > 0)
        Child = self.find(XPathStr)
        # if(len(Children) > 1):
        #    prettyoutput.LogErr("Multiple nodes found fitting criteria: " + XPathStr)
        #    return Children

        # if len(Children) == 0:
        #    return None

        if Child is None:
            return None

        return Child

    def Contains(self, Element):
        for c in self:
            for k, v in c.attrib:
                if k == 'CreationDate':
                    continue
                if k in self.attrib:
                    if not v == self.attrib[k]:
                        return False
        return True

    def UpdateOrAddChildByAttrib(self, Element, AttribNames=None):
        if(AttribNames is None):
            AttribNames = ['Name']
        elif isinstance(AttribNames, str):
            AttribNames = [AttribNames]
        elif not isinstance(AttribNames, list):
            raise Exception("Unexpected attribute names for UpdateOrAddChildByAttrib")

        attribXPathTemplate = "@%(AttribName)s='%(AttribValue)s'"
        attribXPaths = []
        for AttribName in AttribNames:
            val = Element.attrib[AttribName]
            attribXPaths.append(attribXPathTemplate % {'AttribName' : AttribName,
                                                       'AttribValue' : val})

        XPathStr = "%(ElementName)s[%(QueryString)s]" % {'ElementName' : Element.tag,
                                                         'QueryString' : ' and '.join(attribXPaths)}
        return self.UpdateOrAddChild(Element, XPathStr)

    def UpdateOrAddChild(self, Element, XPath=None):
        '''Adds an element using the specified XPath.  If the XPath is unspecified the element name is used
           Returns a tuple with (True/False, Element).
           True indicates the element did not exist and was added.
           False indicates the element existed and the existing value is returned.
           '''

        if(XPath is None):
            XPath = Element.tag

        NewNodeCreated = False

        '''Eliminates duplicates if they are found'''
#        if self.Contains(Element):
#            return
        # MatchingChildren = list(self.findall(XPath))
        # if(len(MatchingChildren) > 1):
            # for i in range(1,len(MatchingChiElement.Parent = selfdren)):
                # self.remove(MatchingChildren[i])

        '''Returns the existing element if it exists, adds ChildElement with specified attributes if it does not exist.'''
        Child = self.find(XPath)
        if Child is None:
            if not Element is None:
                self.append(Element)
                assert(Element in self)
                Child = Element
                NewNodeCreated = True
            else:
                # No data provided to create the child element
                return (False, None)

        # Make sure the parent is set correctly
        VolumeManager.WrapElement(Child)
        Child.Parent = self

        return (NewNodeCreated, Child)
    
    def AddChild(self, new_child_element):
        return self.append(new_child_element)

    def append(self, Child):
        assert(not self == Child)
        super(XElementWrapper, self).append(Child)
        Child.Parent = self
        assert(Child in self)


    def FindParent(self, ParentTag):
        '''Find parent with specified tag'''
        assert (not ParentTag is None)
        P = self._Parent
        while P is not None:
            if(P.tag == ParentTag):
                return P
            P = P._Parent
        return None

    def FindFromParent(self, xpath):
        '''Run find on xpath on each parent, return first hit'''
#        assert (not ParentTag is None)
        P = self._Parent
        while P is not None:
            result = P.find(xpath)
            if not result is None:
                return result

            P = P._Parent
        return None

    def ReplaceChildWithLink(self, child):
        if isinstance(child, XContainerElementWrapper):
            if not child in self:
                return

            LinkElement = XElementWrapper(child.tag + '_Link', attrib=child.attrib)
            # SaveElement.append(LinkElement)
            self.append(LinkElement)
            self.remove(child)



    # replacement for find function that loads subdirectory xml files
    def find(self, xpath):

        (UnlinkedElementsXPath, LinkedElementsXPath, RemainingXPath) = self.__ElementLinkNameFromXPath(xpath)

        matchiterator = super(XElementWrapper, self).iterfind(UnlinkedElementsXPath)
        for match in matchiterator:
            # Run in a loop because find returns the first match, if the first match is invalid look for another
#             NotValid = match.CleanIfInvalid()
#             if NotValid:
#                 continue
#
            if len(RemainingXPath) > 0:
                foundChild = match.find(RemainingXPath)


                # Continue searching links if we don't find a result on the loaded elements
                if not foundChild is None:
                    return foundChild
            else:
                return match

        if not isinstance(self, XContainerElementWrapper):
            return None

        SubContainersIterator = super(XElementWrapper, self).findall(LinkedElementsXPath)

        if SubContainersIterator is None:
            return None

        # Run in a loop because the match may not exist on the first element returned by find
        for SubContainer in SubContainersIterator:

            # Remove the linked element from ourselves, we are about to load it for real.
            self.remove(SubContainer)

            SubContainerPath = os.path.join(self.FullPath, SubContainer.attrib["Path"])

            # OK, open the subcontainer, add it to ourselves as an element and run the rest of the search
            SubContainerElement = self.LoadSubElement(SubContainerPath)
            if(SubContainerElement is None):
                continue

            if len(RemainingXPath) > 0:
                result = SubContainerElement.find(RemainingXPath)
                if not result is None:
                    return result
            else:
                return SubContainerElement

        return None


    def __ElementLinkNameFromXPath(self, xpath):
        # OK, check if we have a linked element to load.

        if '\\' in xpath:
            Logger = logging.getLogger(__name__ + '.' + '__ElementLinkNameFromXPath')
            Logger.warn("Backslash found in xpath query, is this intentional or should it be a forward slash?")
            Logger.warn("XPath: " + xpath)

        parts = xpath.split('/')
        UnlinkedElementsXPath = parts[0]
        SubContainerName = UnlinkedElementsXPath.split('[')[0]
        LinkedSubContainerName = SubContainerName + "_Link"
        LinkedElementsXPath = UnlinkedElementsXPath.replace(SubContainerName, LinkedSubContainerName, 1)
        RemainingXPath = xpath[len(UnlinkedElementsXPath) + 1:]
        return (UnlinkedElementsXPath, LinkedElementsXPath, RemainingXPath)

    def _replace_link(self, link_node):
        '''Replace the link_node, removing it from our element.  Insert the linked directory'''
        self.remove(link_node)
        SubContainerPath = os.path.join(self.FullPath, link_node.attrib["Path"])
        return self.LoadSubElement(SubContainerPath)
        

    def findall(self, match):

        (UnlinkedElementsXPath, LinkedElementsXPath, RemainingXPath) = self.__ElementLinkNameFromXPath(match)

        # TODO: Need to modify to only search one level at a time
        # OK, check for linked elements that also meet the criteria

        LinkMatches = super(XElementWrapper, self).findall(LinkedElementsXPath)
        if LinkMatches is None:
            return  # matches

        for link_node in LinkMatches:
            self._replace_link(link_node)

        # return matches
        matches = super(XElementWrapper, self).findall(UnlinkedElementsXPath)

        for m in matches:
#             NotValid = m.CleanIfInvalid()
#             if NotValid:
#                 continue
            if '_Link' in m.tag:
                m_replaced = self._replace_link(m)
                if m_replaced is None:
                    continue
                else: 
                    m = m_replaced
                
            if len(RemainingXPath) > 0:
                subContainerMatches = m.findall(RemainingXPath)
                if subContainerMatches is not None:
                    for m in subContainerMatches:
                        yield m
            else:
                yield m

    def LoadAllLinkedNodes(self):
        '''Recursively load all of the linked nodes on this element'''
        
        child_nodes = list(self)
        for n in child_nodes:
            if n.tag.endswith('_Link'):
                n_replaced = self._replace_link(n)
                if n_replaced is None:
                    continue
                n = n_replaced

                n.LoadAllLinkedNodes()

        return

class XResourceElementWrapper(VMH.Lockable, XElementWrapper):
    '''Wrapper for an XML element that refers to a file or directory'''

    @property
    def Path(self):
        return self.attrib.get('Path', '')

    @Path.setter
    def Path(self, val):
        self.attrib['Path'] = val

        if hasattr(self, '__fullpath'):
            del self.__dict__['__fullpath']

    @property
    def FullPath(self):

        FullPathStr = self.__dict__.get('__fullpath', None)

        if FullPathStr is None:
            FullPathStr = self.Path

            if(not hasattr(self, '_Parent')):
                return FullPathStr

            IterElem = self.Parent

            while not IterElem is None:
                if hasattr(IterElem, 'FullPath'):
                    FullPathStr = os.path.join(IterElem.FullPath, FullPathStr)
                    IterElem = None
                    break

                elif hasattr(IterElem, '_Parent'):
                    IterElem = IterElem._Parent
                else:
                    raise Exception("FullPath could not be generated for resource")

            if os.path.isdir(FullPathStr):  # Don't create a directory for files
                if not os.path.exists(FullPathStr):
                    prettyoutput.Log("Creating missing directory for FullPath: " + FullPathStr)
                    os.makedirs(FullPathStr)

#            if not os.path.isdir(FullPathStr): #Don't create a directory for files
#                if not os.path.exists(FullPathStr):
#                    prettyoutput.Log("Creating missing directory for FullPath: " + FullPathStr)
#                    os.makedirs(FullPathStr)
#            else:
#                dirname = os.path.dirname(FullPathStr)
#                if not os.path.exists(dirname):
#                    prettyoutput.Log("Creating missing directory for FullPath: " + FullPathStr)
#                    os.makedirs(dirname)

            self.__dict__['__fullpath'] = FullPathStr

        return FullPathStr

    PropertyElementName = 'Properties'

    @property
    def Properties(self):
        PropertyNode = self.find(XContainerElementWrapper.PropertyElementName)
        if(PropertyNode is None):
            PropertyNode = XPropertiesElementWrapper.wrap(ElementTree.Element(XContainerElementWrapper.PropertyElementName))
            self.append(PropertyNode)
        else:
            XPropertiesElementWrapper.wrap(PropertyNode)

        assert(isinstance(PropertyNode, XPropertiesElementWrapper))

        return PropertyNode

    def ToElementString(self):
        outStr = self.FullPath
        return outStr

    def Clean(self, reason=None):
        if self.Locked:
            Logger = logging.getLogger(__name__ + '.' + 'Clean')
            Logger.warning('Could not delete resource with locked flag set: %s' % self.FullPath)
            if not reason is None:
                Logger.warning('Reason for attempt: %s' % reason)
            return
            
        '''Remove the contents referred to by this node from the disk'''
        if os.path.exists(self.FullPath):
            try:
                if os.path.isdir(self.FullPath):
                    shutil.rmtree(self.FullPath)
                else:
                    os.remove(self.FullPath)
            except:
                Logger = logging.getLogger(__name__ + '.' + 'Clean')
                Logger.warning('Could not delete cleaned directory: ' + self.FullPath)

        return super(XResourceElementWrapper, self).Clean(reason=reason)

class XFileElementWrapper(XResourceElementWrapper):
    '''Refers to a file generated by the pipeline'''

    @property
    def Name(self):

        if not 'Name' in self.attrib:
            return self._GetAttribFromParent('Name')

        return self.attrib['Name']

    @Name.setter
    def Name(self, value):
        self.attrib['Name'] = value


    @property
    def Type(self):
        if not 'Type' in self.attrib:
            return self._GetAttribFromParent('Type')

        return self.attrib['Type']

    @Type.setter
    def Type(self, value):
        self.attrib['Type'] = value

    @property
    def Path(self):
        return self.attrib.get('Path', '')

    @Path.setter
    def Path(self, val):
        self.attrib['Path'] = val
        directory = os.path.dirname(self.FullPath)

        if not os.path.exists(directory):
            os.makedirs(directory)

        if hasattr(self, '__fullpath'):
            del self.__dict__['__fullpath']
        return

    def IsValid(self):
        if not os.path.exists(self.FullPath):
            return [False, 'File does not exist']

        return super(XFileElementWrapper, self).IsValid()

    def __init__(self, tag, Path, attrib, **extra):
        super(XFileElementWrapper, self).__init__(tag=tag, attrib=attrib, **extra)
        self.attrib['Path'] = Path

    @property
    def Checksum(self):
        '''Checksum of the file resource when the node was last updated'''
        checksum = self.get('Checksum', None)
        if checksum is None:
            if os.path.exists(self.FullPath):
                checksum = nornir_shared.checksum.FileChecksum(self.FullPath)
                self.attrib['Checksum'] = str(checksum)

        return checksum
    
    
class XContainerElementWrapper(XResourceElementWrapper):
    '''XML meta-data for a container whose sub-elements are contained within a directory on the file system.  The directories container will always be the same, such as TilePyramid'''

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''

        tag = self.tag
        if tag.endswith("_Link"):
            tag = tag[:-len("_Link")]
            tag = tag + "Node"

            current_module = sys.modules[__name__]
            if hasattr(current_module, tag):
                tagClass = getattr(current_module, tag)
                # nornir_shared.Reflection.get_class(tag)

                if not tagClass is None:
                    if hasattr(tagClass, "ClassSortKey"):
                        return tagClass.ClassSortKey(self)

        return self.tag
    
    @property
    def Path(self):
        return self.attrib.get('Path', '')

    @Path.setter
    def Path(self, val):

        super(XContainerElementWrapper, self.__class__).Path.fset(self, val)

        if not os.path.isdir(self.FullPath):
            assert not os.path.isfile(self.FullPath)  # , "Container element path attribute refers to a file.  Remove any '.' from names if it is a directory")
            os.makedirs(self.FullPath)

        return

    def IsValid(self):
        ResourcePath = self.FullPath
        if not os.path.isdir(ResourcePath):
            return [False, 'Directory does not exist']
        elif not self.Parent is None:
            if len(os.listdir(ResourcePath)) == 0:
                return [False, 'Directory is empty']

        return super(XContainerElementWrapper, self).IsValid()

    def UpdateSubElements(self):
        '''Recursively searches directories for VolumeData.xml files.
           Adds discovered nodes into the volume. 
           Removes missing nodes from the volume.'''

        dirNames = os.listdir(self.FullPath)
        
        for dirname in dirNames:
            volumeDataFullPath = os.path.join(dirname, "VolumeData.xml")
            if os.path.exists(volumeDataFullPath):
                # Check to be sure that this is a new node
                existingChild = self.find("[@Path='" + os.path.basename(dirname) + "']")

                if not existingChild is None:
                    continue

                # Load the VolumeData.xml, take the root element name and create a link in our element
                self.LoadSubElement(volumeDataFullPath)

        for child in self:
            if hasattr(child, "UpdateSubElements"):
                child.UpdateSubElements()

        self.CleanIfInvalid()
        self.Save(recurse=False)

    def LoadSubElement(self, Path):
        logger = logging.getLogger(__name__ + '.' + 'LoadSubElement')
        Filename = os.path.join(Path, "VolumeData.xml")
        if not os.path.exists(Filename):
            logger.error(Filename + " does not exist")
            return None

        # print Filename
        try:
            XMLTree = ElementTree.parse(Filename)
        except Exception as e:
            logger.error("Parse error for " + Filename)
            logger.error(str(e))
            return None

        XMLElement = XMLTree.getroot()

        VolumeManager.WrapElement(XMLElement)
        # SubContainer = XContainerElementWrapper.wrap(XMLElement)

        VolumeManager.__SetElementParent__(XMLElement, self)

        self.append(XMLElement)

        Cleaned = XMLElement.CleanIfInvalid()
        if Cleaned:
            return None

        return XMLElement


    def __init__(self, tag, path, attrib=None, **extra):

        if(attrib is None):
            attrib = {}

        super(XContainerElementWrapper, self).__init__(tag=tag, attrib=attrib, **extra)
 
        self.attrib['Path'] = path



    def Save(self, tabLevel=None, recurse=True):
        '''If recurse = False we only save this element, no child elements are saved'''
        
        if tabLevel is None:
            tabLevel = 0
            if hasattr(self, 'FullPath'):
                logger = logging.getLogger(__name__ + '.' + 'Save')
                logger.info("Saving " + self.FullPath)

        self.sort()

        # pool = Pools.GetGlobalThreadPool()
         
        # tabs = '\t' * tabLevel

        # if hasattr(self, 'FullPath'):
        #    logger.info("Saving " + self.FullPath)

        # logger.info('Saving ' + tabs + str(self))
        xmlfilename = 'VolumeData.xml'

        # Create a copy of ourselves for saving.  If this is not done we have the potential to change a collection during iteration
        # which would break the pipeline manager in subtle ways
        SaveElement = ElementTree.Element(self.tag, attrib=self.attrib)
        if(not self.text is None):
            SaveElement.text = self.text

        ValidateAttributesAreStrings(self)

        # SaveTree = ElementTree.ElementTree(SaveElement)

        # Any child containers we create a link to and remove from our file
        for i in range(len(self) - 1, -1, -1):
            child = self[i]
            if child.tag.endswith('_Link'):
                SaveElement.append(child)
                continue

            if isinstance(child, XContainerElementWrapper):
                LinkElement = XElementWrapper(child.tag + '_Link', attrib=child.attrib)
                # SaveElement.append(LinkElement)
                SaveElement.append(LinkElement)

                if(recurse):
                    child.Save(tabLevel + 1)

                # logger.warn("Unloading " + child.tag)
                # del self[i]
                # self.append(LinkElement)
            else:
                if isinstance(SaveElement, XElementWrapper):
                    ValidateAttributesAreStrings(SaveElement)
                    SaveElement.sort()

                SaveElement.append(child)

        self.__SaveXML(xmlfilename, SaveElement)
#        pool.add_task("Saving self.FullPath",   self.__SaveXML, xmlfilename, SaveElement)

        # If we are the root of all saves then make sure they have all completed before returning
        # if(tabLevel == 0 or recurse==False):
            # pool.wait_completion()


    def __SaveXML(self, xmlfilename, SaveElement):
        '''Intended to be called on a thread from the save function'''
        if not os.path.exists(self.FullPath):
            os.makedirs(self.FullPath)

        # prettyoutput.Log("Saving %s" % xmlfilename)

        XMLFilename = os.path.join(self.FullPath, xmlfilename)

        # prettyoutput.Log("Saving %s" % XMLFilename)
        
        OutputXML = ElementTree.tostring(SaveElement, encoding="utf-8")
        # print OutputXML
        with open(XMLFilename, 'w') as hFile:
            hFile.write(OutputXML)
            hFile.close()


class XNamedContainerElementWrapped(XContainerElementWrapper):
    '''XML meta-data for a container whose sub-elements are contained within a directory on the file system whose name is not constant.  Such as a channel name.'''
    
    @property
    def Name(self):
        return self.get('Name', '')

    @Name.setter
    def Name(self, Value):
        self.attrib['Name'] = Value

    def __init__(self, tag, Name, Path=None, attrib=None, **extra):

        if Path is None:
            Path = Name

        if attrib is None:
            attrib = {}

        super(XNamedContainerElementWrapped, self).__init__(tag=tag, path=Path, attrib=attrib, **extra)

        self.attrib['Name'] = Name 

class XLinkedContainerElementWrapper(XContainerElementWrapper):
    '''Child elements of XLinkedContainerElementWrapper are saved
       individually in subdirectories and replaced with an element
       postpended with the name "_link".  This greatly speeds Pythons
       glacially slow XML writing by limiting the amount of XML
       generated'''


    def Save(self, tabLevel=None, recurse=True):
        '''If recurse = False we only save this element, no child elements are saved'''

        if tabLevel is None:
            tabLevel = 0

        self.sort()

        # pool = Pools.GetGlobalThreadPool()

        logger = logging.getLogger(__name__ + '.' + 'XLinkedContainerElementWrapper')
        # tabs = '\t' * tabLevel
        # logger.info('Saving ' + tabs + str(self))
        xmlfilename = 'VolumeData.xml'
        # Create a copy of ourselves for saving
        SaveElement = ElementTree.Element(self.tag, attrib=self.attrib)
        if(not self.text is None):
            SaveElement.text = self.text

        ValidateAttributesAreStrings(self, logger)

        # SaveTree = ElementTree.ElementTree(SaveElement)

        # Any child containers we create a link to and remove from our file
        for i in range(len(self) - 1, -1, -1):
            child = self[i]
            if child.tag.endswith('_Link'):
                SaveElement.append(child)
                continue

            if isinstance(child, XContainerElementWrapper):
                LinkElement = XElementWrapper(child.tag + '_Link', attrib=child.attrib)
                # SaveElement.append(LinkElement)
                SaveElement.append(LinkElement)

                if(recurse):
                    child.Save(tabLevel + 1)

                # logger.warn("Unloading " + child.tag)
                # del self[i]
                # self.append(LinkElement)
            else:
                if isinstance(SaveElement, XElementWrapper):
                    ValidateAttributesAreStrings(SaveElement, logger)
                    SaveElement.sort()

                SaveElement.append(child)

        self.__SaveXML(xmlfilename, SaveElement)
#        pool.add_task("Saving self.FullPath",   self.__SaveXML, xmlfilename, SaveElement)

        # If we are the root of all saves then make sure they have all completed before returning
        # if(tabLevel == 0 or recurse==False):
            # pool.wait_completion()


class BlockNode(XNamedContainerElementWrapped):

    @property
    def Sections(self):
        return self.findall('Section')

    @property
    def StosGroups(self):
        return list(self.findall('StosGroup'));

    @property
    def StosMaps(self):
        return list(self.findall('StosMap'));

    def GetSection(self, Number):
        return self.GetChildByAttrib('Section', 'Number', Number)

    def GetOrCreateSection(self, Number):
        sectionObj = self.GetSection(Number) 

        if sectionObj is None:
            SectionName = ('%' + nornir_buildmanager.templates.Current.SectionFormat) % Number
            SectionPath = ('%' + nornir_buildmanager.templates.Current.SectionFormat) % Number
            
            sectionObj = SectionNode(Number,
                                     SectionName,
                                     SectionPath)
            return self.UpdateOrAddChildByAttrib(sectionObj, 'Number')
        else:
            return (False, sectionObj)
    
    def GetStosGroup(self, group_name, downsample):
        for stos_group in self.findall("StosGroup[@Name='%s']" % group_name):
            if stos_group.Downsample == downsample:
                return stos_group
            
        return None
    
    def GetOrCreateStosGroup(self, group_name, downsample):
        ''':Return: Tuple of (created, stos_group)'''
        
        existing_stos_group = self.GetStosGroup(group_name, downsample)
        if not existing_stos_group is None:
            return (False, existing_stos_group)
        
        OutputStosGroupNode = StosGroupNode(group_name, Downsample=downsample)
        self.AddChild(OutputStosGroupNode)
            
        return (True, OutputStosGroupNode)
    
    def GetStosMap(self, map_name):
        return self.GetChildByAttrib('StosMap', 'Name', map_name)
    
    def GetOrCreateStosMap(self, map_name):
        stos_map_node = self.GetStosMap(map_name)
        if stos_map_node is None:
            stos_map_node = self.AddChild(StosMapNode(map_name))
        else:
            return stos_map_node
        
    def RemoveStosMap(self, map_name):
        ''':return: True if a map was found and removed'''
        stos_map_node = self.GetStosMap(map_name)
        if not stos_map_node is None:
            self.remove(stos_map_node)
            return True
        
        return False
    
    def RemoveStosGroup(self, group_name, downsample):
        ''':return: True if a StosGroup was found and removed'''
        existing_stos_group = self.GetStosGroup(group_name, downsample)
        if not existing_stos_group is None:
            self.remove(existing_stos_group)
            return True
        
        return False
    
    def MarkSectionsAsDamaged(self, section_number_list):
        '''Add the sections in the list to the NonStosSectionNumbers'''
        if not isinstance(section_number_list, set) or isinstance(section_number_list, frozenset):
            section_number_list = frozenset(section_number_list)
            
        existing_set = frozenset(self.NonStosSectionNumbers)
        self.NonStosSectionNumbers = section_number_list.union(existing_set)
        
    def MarkSectionsAsUndamaged(self, section_number_list):
        if not isinstance(section_number_list, set) or isinstance(section_number_list, frozenset):
            section_number_list = frozenset(section_number_list)
            
        existing_set = frozenset(self.NonStosSectionNumbers)
        self.NonStosSectionNumbers = existing_set.difference(section_number_list)
    
    @property
    def NonStosSectionNumbers(self):
        '''A list of integers indicating which section numbers should not be control sections for slice to slice registration'''
        StosExemptNode = XElementWrapper(tag='NonStosSectionNumbers')
        (added, StosExemptNode) = self.UpdateOrAddChild(StosExemptNode)
    
        # Fetch the list of the exempt nodes from the element text
        ExemptString = StosExemptNode.text
    
        if(ExemptString is None or len(ExemptString) == 0):
            return []
    
        # OK, parse the exempt string to a different list
        NonStosSectionNumbers = sorted(frozenset([int(x) for x in ExemptString.split(',')]))
    
        return NonStosSectionNumbers
    
    @NonStosSectionNumbers.setter
    def NonStosSectionNumbers(self, value):
        '''A list of integers indicating which section numbers should not be control sections for slice to slice registration'''
        StosExemptNode = XElementWrapper(tag='NonStosSectionNumbers')
        (added, StosExemptNode) = self.UpdateOrAddChild(StosExemptNode)
        
        if isinstance(value, str):
            StosExemptNode.text = value
        elif isinstance(value, list) or isinstance(value, set) or isinstance(value, frozenset):
            StosExemptNode.text = ','.join(list(map(str, value)))
       

    def __init__(self, Name, Path=None, attrib=None, **extra):
        super(BlockNode, self).__init__(tag='Block', Name=Name, Path=Path, attrib=attrib, **extra)


class ChannelNode(XNamedContainerElementWrapped):

    @property
    def Filters(self):
        return self.findall('Filter')

    def GetFilter(self, Filter):
        return self.GetChildByAttrib('Filter', 'Name', Filter)
    
    def HasFilter(self, FilterName):
        return not self.GetFilter(FilterName) is None

    def GetOrCreateFilter(self, Name):
        (added, filterNode) = self.UpdateOrAddChildByAttrib(FilterNode(Name), 'Name')
        return (added, filterNode)

    def MatchFilterPattern(self, filterPattern):
        return VMH.SearchCollection(self.Filters,
                                   'Name',
                                    filterPattern)

    def GetTransform(self, transform_name):
        return self.GetChildByAttrib('Transform', 'Name', transform_name)

    def RemoveFilterOnContrastMismatch(self, FilterName, MinIntensityCutoff, MaxIntensityCutoff, Gamma):
        '''
        Return: true if filter found and removed
        '''

        filter_node = self.GetFilter(Filter=FilterName)
        if filter_node is None:
            return False

        if filter_node.Locked:
            if filter_node.IsContrastMismatched(MinIntensityCutoff, MaxIntensityCutoff, Gamma):
                self.logger.warn("Locked filter cannot be removed for contrast mismatch. %s " % filter_node.FullPath)
                return False 

        return filter_node.RemoveNodeOnContrastMismatch(MinIntensityCutoff, MaxIntensityCutoff, Gamma)

    def GetScale(self):
        return self.find('Scale')

    def SetScale(self, scaleValueInNm):
        '''Create a scale node for the channel
        :return: ScaleNode object that was created'''
        # TODO: Scale should be its own object and a property
        [added, ScaleObj] = self.UpdateOrAddChild(XElementWrapper('Scale'))

        ScaleObj.UpdateOrAddChild(XElementWrapper('X', {'UnitsOfMeasure' : 'nm',
                                                             'UnitsPerPixel' : str(scaleValueInNm)}))
        ScaleObj.UpdateOrAddChild(XElementWrapper('Y', {'UnitsOfMeasure' : 'nm',
                                                             'UnitsPerPixel' : str(scaleValueInNm)}))
        return (added, ScaleObj)

    def __init__(self, Name, Path=None, attrib=None, **extra):
        super(ChannelNode, self).__init__(tag='Channel', Name=Name, Path=Path, attrib=attrib, **extra)


class ScaleNode(XElementWrapper):

    @property
    def X(self):
        x_elem = self.find('X')

        if x_elem is None:
            return None

        return ScaleAxis(x_elem.UnitsPerPixel, x_elem.UnitsOfMeasure)

    @property
    def Y(self):
        y_elem = self.find('Y')

        if y_elem is None:
            return None

        return ScaleAxis(y_elem.UnitsPerPixel, y_elem.UnitsOfMeasure)

    @property
    def Z(self):
        z_elem = self.find('Z')

        if z_elem is None:
            return None

        return ScaleAxis(z_elem.UnitsPerPixel, z_elem.UnitsOfMeasure)

    def __init__(self, attrib=None, **extra):
        super(ScaleNode, self).__init__(tag='Scale', attrib=attrib, **extra)

class ScaleAxis:

    def __init__(self, UnitsPerPixel, UnitsOfMeasure):
        self.UnitsPerPixel = float(UnitsPerPixel)
        self.UnitsOfMeasure = str(UnitsOfMeasure)


def BuildFilterImageName(SectionNumber, ChannelName, FilterName, Extension=None):
    return nornir_buildmanager.templates.Current.SectionTemplate % int(SectionNumber) + "_" + ChannelName + "_" + FilterName + Extension

class FilterNode(XNamedContainerElementWrapped, VMH.ContrastHandler):

    DefaultMaskName = "Mask"

    def DefaultImageName(self, extension):
        '''Default name for an image in this filters imageset'''
        InputChannelNode = self.FindParent('Channel')
        section_node = InputChannelNode.FindParent('Section')
        return BuildFilterImageName(section_node.Number, InputChannelNode.Name, self.Name, extension)

    @property
    def Histogram(self):
        '''Get the image set for the filter, create if missing'''
        # imageset = self.GetChildByAttrib('ImageSet', 'Name', ImageSetNode.Name)
        # There should be only one Imageset, so use find
        histogram = self.find('Histogram')
        if histogram is None:
            histogram = HistogramNode()
            self.append(histogram)

        return histogram
    @property
    def BitsPerPixel(self):
        if 'BitsPerPixel' in self.attrib:
            return int(self.attrib['BitsPerPixel'])
        return None

    @BitsPerPixel.setter
    def BitsPerPixel(self, val):
        self.attrib['BitsPerPixel'] = '%d' % val
        

    def GetOrCreateTilePyramid(self):
        # pyramid = self.GetChildByAttrib('TilePyramid', "Name", TilePyramidNode.Name)
        # There should be only one Imageset, so use find
        pyramid = self.find('TilePyramid')
        if pyramid is None:
            pyramid = TilePyramidNode(NumberOfTiles=0)
            self.append(pyramid)
            return (True, pyramid)
        else:
            return (False, pyramid)

    @property
    def TilePyramid(self):
        # pyramid = self.GetChildByAttrib('TilePyramid', "Name", TilePyramidNode.Name)
        # There should be only one Imageset, so use find
        pyramid = self.find('TilePyramid')
        if pyramid is None:
            pyramid = TilePyramidNode(NumberOfTiles=0)
            self.append(pyramid)

        return pyramid
    
    @property
    def HasTilePyramid(self):
        return not self.find('TilePyramid') is None
    
    @property
    def HasImageset(self):
        return not self.find('ImageSet') is None
    
    @property
    def HasTileset(self):
        return not self.find('Tileset') is None

    @property
    def Imageset(self):
        '''Get the image set for the filter, create if missing'''
        # imageset = self.GetChildByAttrib('ImageSet', 'Name', ImageSetNode.Name)
        # There should be only one Imageset, so use find
        imageset = self.find('ImageSet')
        if imageset is None:
            imageset = ImageSetNode()
            self.append(imageset)

        return imageset
    
    @property
    def MaskImageset(self):
        '''Get the imageset for the default mask'''
        
        maskFilter = self.GetMaskFilter()
        if maskFilter is None:
            return None
        
        return maskFilter.Imageset

    @property
    def MaskName(self):
        '''The default mask to use for this filter'''
        m = self.attrib.get("MaskName", None)
        if not m is None:
            if len(m) == 0:
                m = None

        return m

    @MaskName.setter
    def MaskName(self, val):
        if val is None:
            if 'MaskName' in self.attrib:
                del self.attrib['MaskName']
        else:
            self.attrib['MaskName'] = val
            
            
    def GetOrCreateMaskName(self):
        '''Returns the maskname for the filter, if it does not exist use the default mask name'''
        if self.MaskName is None:
            self.MaskName = FilterNode.DefaultMaskName 
            
        return self.MaskName
            
    @property
    def HasMask(self):
        '''
        :return: True if the mask filter exists
        '''
        return not self.GetMaskFilter() is None
    
    
    def GetMaskFilter(self, MaskName=None):
        if MaskName is None:
            MaskName = self.MaskName
            
        if MaskName is None:
            return None
        
        assert(isinstance(MaskName, str))

        return self.Parent.GetFilter(MaskName)
    

    def GetOrCreateMaskFilter(self, MaskName=None):
        if MaskName is None:
            MaskName = self.GetOrCreateMaskName()
            
        assert(isinstance(MaskName, str))

        return self.Parent.GetOrCreateFilter(MaskName)


    def GetImage(self, Downsample):
        if not self.HasImageset:
            return None
        
        return self.Imageset.GetImage(Downsample)


    def GetOrCreateImage(self, Downsample):
        imageset = self.Imageset
        return imageset.GetOrCreateImage(Downsample)


    def GetMaskImage(self, Downsample):
        maskFilter = self.GetMaskFilter()
        if maskFilter is None:
            return None

        return maskFilter.GetImage(Downsample)


    def GetOrCreateMaskImage(self, Downsample):
        (added_mask_filter, maskFilter) = self.GetOrCreateMaskFilter()
        return maskFilter.GetOrCreateImage(Downsample)

    def GetHistogram(self):
        return self.find('Histogram')

    def __init__(self, Name, Path=None, attrib=None, **extra):
        if Path is None:
            Path = Name

        super(FilterNode, self).__init__(tag='Filter', Name=Name, Path=Path, attrib=attrib, **extra)
                
    def _LogContrastMismatch(self, MinIntensityCutoff, MaxIntensityCutoff, Gamma):
        XElementWrapper.logger.warn("\tCurrent values (%g,%g,%g), target (%g,%g,%g)" % (self.MinIntensityCutoff, self.MaxIntensityCutoff, self.Gamma, MinIntensityCutoff, MaxIntensityCutoff, Gamma))

class NotesNode(XResourceElementWrapper):

    def __init__(self, Text=None, SourceFilename=None, attrib=None, **extra):

        super(NotesNode, self).__init__(tag='Notes', attrib=attrib, **extra)

        if not Text is None:
            self.text = Text

        if not SourceFilename is None:
            self.SourceFilename = SourceFilename
            self.Path = os.path.basename(SourceFilename)
        else:
            self.SourceFilename = ""
            self.Path = os.path.basename(SourceFilename)


    def CleanIfInvalid(self):
        return False


class SectionNode(XNamedContainerElementWrapped):

    @classmethod
    def ClassSortKey(cls, self):
        '''Required for objects derived from XContainerElementWrapper'''
        return "Section " + (nornir_buildmanager.templates.Current.SectionTemplate % int(self.Number))

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return SectionNode.ClassSortKey(self)

    @property
    def Channels(self):
        return self.findall('Channel')

    @property
    def Number(self):
        return int(self.get('Number', '0'))

    @Number.setter
    def Number(self, Value):
        self.attrib['Number'] = str(int(Value))

    def GetChannel(self, Channel):
        return self.GetChildByAttrib('Channel', 'Name', Channel)
    
    def GetOrCreateChannel(self, ChannelName):
        channelObj = self.GetChildByAttrib('Channel', 'Name', ChannelName)
        if channelObj is None:
            channelObj = ChannelNode(ChannelName)
            return self.UpdateOrAddChildByAttrib(channelObj, 'Name')
        else:
            return (False, channelObj)

    def MatchChannelPattern(self, channelPattern):
        return VMH.SearchCollection(self.Channels,
                                             'Name',
                                             channelPattern)

    def MatchChannelFilterPattern(self, channelPattern, filterPattern):
        filterNodes = []
        for channelNode in self.MatchChannelPattern(channelPattern):
            result = channelNode.MatchFilterPattern(filterPattern)
            if not result is None:
                filterNodes.extend(result)

        return filterNodes


    def __init__(self, Number, Name=None, Path=None, attrib=None, **extra):

        if Name is None:
            Name = nornir_buildmanager.templates.Current.SectionTemplate % Number

        if Path is None:
            Path = nornir_buildmanager.templates.Current.SectionTemplate % Number

        super(SectionNode, self).__init__(tag='Section', Name=Name, Path=Path, attrib=attrib, **extra)
        self.Number = Number


class StosGroupNode(XNamedContainerElementWrapped):

    @property
    def Downsample(self):
        return float(self.attrib['Downsample'])

    @Downsample.setter
    def Downsample(self, val):
        '''The default key used for sorting elements'''
        self.attrib['Downsample'] = '%g' % val
        
    @property
    def ManualInputDirectory(self):
        '''Directory that manual override stos files are placed in'''
        return os.path.join(self.FullPath, 'Manual')
        
    def CreateDirectories(self):
        '''Ensures the manual input directory exists'''
        if not os.path.exists(self.FullPath):
            os.makedirs(self.FullPath)
            
        if not os.path.exists(self.ManualInputDirectory):
            os.makedirs(self.ManualInputDirectory)
            
    def PathToManualTransform(self, InputTransformFullPath):
        '''Check the manual directory for the existence of a user-supplied file we should use.
           Returns the path to the file if it exists, otherwise None'''
        
        transform_filename = os.path.basename(InputTransformFullPath)
        # Copy the input stos or converted stos to the input directory
        ManualInputStosFullPath = os.path.join(self.ManualInputDirectory, transform_filename)
        if os.path.exists(ManualInputStosFullPath):
            return ManualInputStosFullPath
    
        return None

    @property
    def SectionMappings(self):
        return list(self.findall('SectionMappings'))

    def GetSectionMapping(self, MappedSectionNumber):
        return self.GetChildByAttrib('SectionMappings', 'MappedSectionNumber', MappedSectionNumber)

    def GetOrCreateSectionMapping(self, MappedSectionNumber):
        (added, sectionMappings) = self.UpdateOrAddChildByAttrib(SectionMappingsNode(MappedSectionNumber=MappedSectionNumber), 'MappedSectionNumber')
        return (added, sectionMappings)

    def TransformsForMapping(self, MappedSectionNumber, ControlSectionNumber):
        sectionMapping = self.GetSectionMapping(MappedSectionNumber)
        if sectionMapping is None:
            return []

        return sectionMapping.TransformsToSection(ControlSectionNumber)


    def GetStosTransformNode(self, ControlFilter, MappedFilter):
        MappedSectionNode = MappedFilter.FindParent("Section")
        MappedChannelNode = MappedFilter.FindParent("Channel")
        ControlSectionNode = ControlFilter.FindParent("Section")
        ControlChannelNode = ControlFilter.FindParent("Channel")

        SectionMappingsNode = self.GetSectionMapping(MappedSectionNode.Number)
        if SectionMappingsNode is None:
            return None
        
        # assert(not SectionMappingsNode is None) #We expect the caller to arrange for a section mappings node in advance

        stosNode = SectionMappingsNode.FindStosTransform(ControlSectionNode.Number,
                                                               ControlChannelNode.Name,
                                                                ControlFilter.Name,
                                                                 MappedSectionNode.Number,
                                                                  MappedChannelNode.Name,
                                                                   MappedFilter.Name)
        
        

        return stosNode

    def GetOrCreateStosTransformNode(self, ControlFilter, MappedFilter, OutputType, OutputPath):
        added = False
        stosNode = self.GetStosTransformNode(ControlFilter, MappedFilter)

        if stosNode is None:
            added = True
            stosNode = self.CreateStosTransformNode(ControlFilter, MappedFilter, OutputType, OutputPath)
        else:
            self.__LegacyUpdateStosNode(stosNode, ControlFilter, MappedFilter, OutputPath)   

        return (added, stosNode)
    
    def  AddChecksumsToStos(self, stosNode, ControlFilter, MappedFilter):
            
        if MappedFilter.Imageset.HasImage(self.Downsample) or MappedFilter.Imageset.CanGenerate(self.Downsample):
            stosNode.attrib['MappedImageChecksum'] = MappedFilter.Imageset.GetOrCreateImage(self.Downsample).Checksum
        else:
            stosNode.attrib['MappedImageChecksum'] = ""
        
        if ControlFilter.Imageset.HasImage(self.Downsample) or ControlFilter.Imageset.CanGenerate(self.Downsample):
            stosNode.attrib['ControlImageChecksum'] = ControlFilter.Imageset.GetOrCreateImage(self.Downsample).Checksum
        else:
            stosNode.attrib['ControlImageChecksum'] = ""
            
        if MappedFilter.HasMask and ControlFilter.HasMask:
            if MappedFilter.MaskImageset.HasImage(self.Downsample) or MappedFilter.MaskImageset.CanGenerate(self.Downsample):
                stosNode.attrib['MappedMaskImageChecksum'] = MappedFilter.MaskImageset.GetOrCreateImage(self.Downsample).Checksum
            else:
                stosNode.attrib['MappedMaskImageChecksum'] = ""
            
            if ControlFilter.MaskImageset.HasImage(self.Downsample) or ControlFilter.MaskImageset.CanGenerate(self.Downsample):
                stosNode.attrib['ControlMaskImageChecksum'] = ControlFilter.MaskImageset.GetOrCreateImage(self.Downsample).Checksum
            else:
                stosNode.attrib['ControlMaskImageChecksum'] = ""


    def CreateStosTransformNode(self, ControlFilter, MappedFilter, OutputType, OutputPath):
        '''
        :param FilterNode ControlFilter: Filter for control image
        :param FilterNode MappedFilter: Filter for mapped image
        :param str OutputType: Type of stosNode
        :Param str OutputPath: Full path to .stos file
        '''
        
        MappedSectionNode = MappedFilter.FindParent("Section")
        MappedChannelNode = MappedFilter.FindParent("Channel")
        ControlSectionNode = ControlFilter.FindParent("Section")
        ControlChannelNode = ControlFilter.FindParent("Channel")
        
        SectionMappingsNode = self.GetSectionMapping(MappedSectionNode.Number)
        assert(not SectionMappingsNode is None)  # We expect the caller to arrange for a section mappings node in advance
               
        stosNode = TransformNode(str(ControlSectionNode.Number), OutputType, OutputPath, {'ControlSectionNumber' : str(ControlSectionNode.Number),
                                                                                        'MappedSectionNumber' : str(MappedSectionNode.Number),
                                                                                        'MappedChannelName' : str(MappedChannelNode.Name),
                                                                                        'MappedFilterName' : str(MappedFilter.Name),
                                                                                        'ControlChannelName' : str(ControlChannelNode.Name),
                                                                                        'ControlFilterName' : str(ControlFilter.Name)})
         
        self.AddChecksumsToStos(stosNode, ControlFilter, MappedFilter)
#        WORKAROUND: The etree implementation has a serious shortcoming in that it cannot handle the 'and' operator in XPath queries.
#        (added, stosNode) = SectionMappingsNode.UpdateOrAddChildByAttrib(stosNode, ['ControlSectionNumber',
#                                                                                    'ControlChannelName',
#                                                                                    'ControlFilterName',
#                                                                                    'MappedSectionNumber',
#                                                                                    'MappedChannelName',
#                                                                                    'MappedFilterName'])

        SectionMappingsNode.append(stosNode)   
       
        return stosNode
    
    @classmethod
    def GenerateStosFilename(cls, ControlFilter, MappedFilter):
    
        ControlSectionNode = ControlFilter.FindParent('Section')
        MappedSectionNode = MappedFilter.FindParent('Section')
    
        OutputFile = str(MappedSectionNode.Number) + '-' + str(ControlSectionNode.Number) + \
                                 '_ctrl-' + ControlFilter.Parent.Name + "_" + ControlFilter.Name + \
                                 '_map-' + MappedFilter.Parent.Name + "_" + MappedFilter.Name + '.stos'
        return OutputFile

    
    
    @classmethod 
    def _IsStosInputImageOutdated(cls, stosNode, ChecksumAttribName, imageNode):
        '''
        :param TransformNode stosNode: Stos Transform Node to test
        :param str ChecksumAttribName: Name of attribute with checksum value on image node
        :param ImageNode imageNode: Image node to test
        '''
                
        if imageNode is None:
            return True
        
        IsInvalid = False
        
        if len(stosNode.attrib.get(ChecksumAttribName, "")) > 0:
            IsInvalid = IsInvalid or not nornir_buildmanager.validation.transforms.IsValueMatched(stosNode, ChecksumAttribName, imageNode.Checksum)
        else:
            if not os.path.exists(imageNode.FullPath):
                IsInvalid = IsInvalid or True
            else:
                IsInvalid = IsInvalid or nornir_shared.files.IsOutdated(imageNode.FullPath, stosNode.FullPath)
            
        return IsInvalid
        
   
    def AreStosInputImagesOutdated(self, stosNode, ControlFilter, MappedFilter, MaskRequired):
        '''
        :param TransformNode stosNode: Stos Transform Node to test
        :param FilterNode ControlFilter: Filter for control image
        :param FilterNode MappedFilter: Filter for mapped image
        :param str OutputType: Type of stosNode
        :Param str OutputPath: Full path to .stos file
        '''
        
        if stosNode is None or ControlFilter is None or MappedFilter is None:
            return True
        
        ControlImageNode = ControlFilter.GetOrCreateImage(self.Downsample)
        MappedImageNode = MappedFilter.GetOrCreateImage(self.Downsample)
        
        IsInvalid = False
        
        IsInvalid = IsInvalid or StosGroupNode._IsStosInputImageOutdated(stosNode, ChecksumAttribName='ControlImageChecksum', imageNode=ControlImageNode)
        IsInvalid = IsInvalid or StosGroupNode._IsStosInputImageOutdated(stosNode, ChecksumAttribName='MappedImageChecksum', imageNode=MappedImageNode)
        
        if MaskRequired:
            ControlMaskImageNode = ControlFilter.GetMaskImage(self.Downsample)
            MappedMaskImageNode = MappedFilter.GetMaskImage(self.Downsample)
            IsInvalid = IsInvalid or StosGroupNode._IsStosInputImageOutdated(stosNode, ChecksumAttribName='ControlMaskImageChecksum', imageNode=ControlMaskImageNode)
            IsInvalid = IsInvalid or StosGroupNode._IsStosInputImageOutdated(stosNode, ChecksumAttribName='MappedMaskImageChecksum', imageNode=MappedMaskImageNode)
         
        return IsInvalid
    
   
    def __LegacyUpdateStosNode(self, stosNode, ControlFilter, MappedFilter, OutputPath):
        
        if stosNode is None:
            return 
        
        if not hasattr(stosNode, "ControlChannelName") or not hasattr(stosNode, "MappedChannelName"):

            MappedChannelNode = MappedFilter.FindParent("Channel")
            ControlChannelNode = ControlFilter.FindParent("Channel")

            renamedPath = os.path.join(os.path.dirname(stosNode.FullPath), stosNode.Path)
            XElementWrapper.logger.warn("Renaming stos transform for backwards compatability")
            XElementWrapper.logger.warn(renamedPath + " -> " + stosNode.FullPath)
            shutil.move(renamedPath, stosNode.FullPath)
            stosNode.Path = OutputPath
            stosNode.MappedChannelName = MappedChannelNode.Name
            stosNode.MappedFilterName = MappedFilter.Name
            stosNode.ControlChannelName = ControlChannelNode.Name
            stosNode.ControlFilterName = ControlFilter.Name
            stosNode.ControlImageChecksum = str(ControlFilter.Imageset.Checksum)
            stosNode.MappedImageChecksum = str(MappedFilter.Imageset.Checksum)

    def __init__(self, Name, Downsample, attrib=None, **extra):

        super(StosGroupNode, self).__init__(tag='StosGroup', Name=Name, Path=Name, attrib=attrib, **extra)
        self.Downsample = Downsample
    
    @property
    def SummaryString(self):
        '''
            :return: Name of the group and the downsample level
            :rtype str:
        '''
        return "{0:s} {1:3d}".format(self.Name.ljust(20), int(self.Downsample))
    
    def CleanIfInvalid(self):
        cleaned = super(StosGroupNode, self).CleanIfInvalid()
        
        #TODO: Deleting stale transforms and section mappinds needs to be enabled, but I identified this shortcoming in a remote and 
        #want to work on it in my own test environment
        #if not cleaned:    
            #for mapping in self.SectionMappings:
                #cleaned or mapping.CleanIfInvalid()
                
        return cleaned
         

class StosMapNode(XElementWrapper):

    @property
    def Name(self):
        return self.get('Name', '')

    @Name.setter
    def Name(self, Value):
        self.attrib['Name'] = Value

    @property
    def Type(self):
        '''Type of Stos Map'''
        m = self.attrib.get("Type", None)

    @Type.setter
    def Type(self, val):
        if val is None:
            if 'Type' in self.attrib:
                del self.attrib['Type']
        else:
            self.attrib['Type'] = val

    @property
    def CenterSection(self):
        if 'CenterSection' in self.attrib:
            val = self.attrib['CenterSection']
            if len(val) == 0:
                return None
            else:
                return int(val)

        return None

    @CenterSection.setter
    def CenterSection(self, val):
        if val is None:
            self.attrib['CenterSection'] = ""
        else:
            assert(isinstance(val, int))
            self.attrib['CenterSection'] = str(val)

    @property
    def Mappings(self):
        return list(self.findall('Mapping'))

    def MappedToControls(self):
        '''Return dictionary of possible control sections for a given mapped section number'''
        MappedToControlCandidateList = {}
        for mappingNode in self.Mappings:
            for mappedSection in mappingNode.Mapped:
                if mappedSection in MappedToControlCandidateList:
                    MappedToControlCandidateList[mappedSection].append(mappingNode.Control)
                else:
                    MappedToControlCandidateList[mappedSection] = [mappingNode.Control]

        return MappedToControlCandidateList

    def GetMappingsForControl(self, Control):
        mappings = self.findall("Mapping[@Control='" + str(Control) + "']")
        if mappings is None:
            return []

        return list(mappings)

    def ClearBannedControlMappings(self, NonStosSectionNumbers):
        '''Remove any control sections from a mapping which cannot be a control'''

        removed = False
        for InvalidControlSection in NonStosSectionNumbers:
            mapNodes = self.GetMappingsForControl(InvalidControlSection)
            for mapNode in mapNodes:
                removed = True
                self.remove(mapNode)

        return removed

    @property
    def AllowDuplicates(self):
        return self.attrib.get('AllowDuplicates', True)
    
    @classmethod
    def _SectionNumberFromParameter(self, input_value):
        val = None
        if isinstance(input_value, nornir_imageregistration.transforms.registrationtree.RegistrationTreeNode):
            val = input_value.SectionNumber
        elif isinstance(input_value, int):
            val = input_value
        else:
            raise TypeError("Section Number parameter should be an integer or RegistrationTreeNode")

        return val

    def AddMapping(self, Control, Mapped):
        '''Create a mapping to a control section'''

        val = StosMapNode._SectionNumberFromParameter(Mapped)
        Control = StosMapNode._SectionNumberFromParameter(Control)

        childMapping = self.GetChildByAttrib('Mapping', 'Control', Control)
        if childMapping is None:
            childMapping = MappingNode(Control, val)
            self.append(childMapping)
        else:
            if not val in childMapping.Mapped:
                childMapping.AddMapping(val)
        return

    def RemoveMapping(self, Control, Mapped):
        '''Remove a mapping
        :return: True if mapped section is found and removed
        '''

        Mapped = StosMapNode._SectionNumberFromParameter(Mapped)
        Control = StosMapNode._SectionNumberFromParameter(Control)

        childMapping = self.GetChildByAttrib('Mapping', 'Control', Control)
        if childMapping is not None:
            if Mapped in childMapping.Mapped:
                childMapping.RemoveMapping(Mapped)

                if len(childMapping.Mapped) == 0:
                    self.remove(childMapping)

                return True

        return False

    def FindAllControlsForMapped(self, MappedSection):
        '''Given a section to be mapped, return the first control section found'''
        for m in self:
            if not m.tag == 'Mapping':
                continue

            if(MappedSection in m.Mapped):
                yield m.Control

        return

    def RemoveDuplicateControlEntries(self, Control):
        '''If there are two entries with the same control number we merge the mapping list and delete the duplicate'''

        mappings = list(self.GetMappingsForControl(Control))
        if len(mappings) < 2:
            return False

        mergeMapping = mappings[0]
        for i in range(1, len(mappings)):
            mappingNode = mappings[i]
            for mappedSection in mappingNode.Mapped:
                mergeMapping.AddMapping(mappedSection)

            self.remove(mappingNode)
            XElementWrapper.logger.warn('Moving duplicate mapping ' + str(Control) + ' <- ' + str(mappedSection))

        return True

    def IsValid(self):
        '''Check for mappings whose control section is in the non-stos section numbers list'''

        if not hasattr(self, 'Parent'):
            return super(StosMapNode, self).IsValid()

        NonStosSectionsNode = self.Parent.find('NonStosSectionNumbers')

        AlreadyMappedSections = []

        if NonStosSectionsNode is None:
            return super(StosMapNode, self).IsValid()

        NonStosSections = misc.ListFromAttribute(NonStosSectionsNode.text)

        MappingNodes = list(self.findall('Mapping'))

        for i in range(len(MappingNodes) - 1, -1, -1):
            Mapping = MappingNodes[i]
            self.RemoveDuplicateControlEntries(Mapping.Control)

        MappingNodes = list(self.findall('Mapping'))

        for i in range(len(MappingNodes) - 1, -1, -1):
            Mapping = MappingNodes[i]

            if Mapping.Control in NonStosSections:
                Mapping.Clean()
                XElementWrapper.logger.warn('Mappings for control section ' + str(Mapping.Control) + ' removed due to existence in NonStosSectionNumbers element')
            else:
                MappedSections = Mapping.Mapped
                for i in range(len(MappedSections) - 1, -1, -1):
                    MappedSection = MappedSections[i]
                    if MappedSection in AlreadyMappedSections and not self.AllowDuplicates:
                        del MappedSections[i]
                        XElementWrapper.logger.warn('Removing duplicate mapping ' + str(MappedSection) + ' -> ' + str(Mapping.Control))
                    else:
                        AlreadyMappedSections.append(MappedSection)

                if len(MappedSections) == 0:
                    Mapping.Clean()
                    XElementWrapper.logger.warn('No mappings remain for control section ' + str(Mapping.Control))
                elif len(MappedSections) != Mapping.Mapped:
                    Mapping.Mapped = MappedSections


        return super(StosMapNode, self).IsValid()

    def __init__(self, Name, attrib=None, **extra):

        super(StosMapNode, self).__init__(tag='StosMap', Name=Name, attrib=attrib, **extra)




class MappingNode(XElementWrapper):

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return self.tag + ' ' + (nornir_buildmanager.templates.Current.SectionTemplate % self.Control)

    @property
    def Control(self):
        return int(self.attrib['Control'])

    @property
    def Mapped(self):
        mappedList = misc.ListFromAttribute(self.get('Mapped', []))
        mappedList.sort()
        return mappedList

    @Mapped.setter
    def Mapped(self, value):
        AdjacentSectionString = ''
        if isinstance(value, list):
            value.sort()
            AdjacentSectionString = ','.join(str(x) for x in value)
        else:
            assert(isinstance(value, int))
            AdjacentSectionString = str(value)

        self.attrib['Mapped'] = AdjacentSectionString

    def AddMapping(self, value):
        intval = int(value)
        Mappings = self.Mapped
        if intval in Mappings:
            return
        else:
            Mappings.append(value)
            self.Mapped = Mappings

    def RemoveMapping(self, value):
        intval = int(value)
        Mappings = self.Mapped
        Mappings.remove(intval)
        self.Mapped = Mappings


    def __str__(self):
        return "%d <- %s" % (self.Control, str(self.Mapped))


    def __init__(self, ControlNumber, MappedNumbers, attrib=None, **extra):
        super(MappingNode, self).__init__(tag='Mapping', attrib=attrib, **extra)

        self.attrib['Control'] = str(ControlNumber)

        if not MappedNumbers is None:
            self.Mapped = MappedNumbers


class MosaicBaseNode(XFileElementWrapper):

    @classmethod
    def GetFilename(cls, Name, Type):
        Path = Name + Type + '.mosaic'
        return Path

    def _CalcChecksum(self):
        (file, ext) = os.path.splitext(self.Path)
        ext = ext.lower()

        if not os.path.exists(self.FullPath):
            return None

        if ext == '.stos':
            return stosfile.StosFile.LoadChecksum(self.FullPath)
        elif ext == '.mosaic':
            return mosaicfile.MosaicFile.LoadChecksum(self.FullPath)
        else:
            raise Exception("Cannot compute checksum for unknown transform type")

        return None

    def ResetChecksum(self):
        '''Recalculate the checksum for the element'''
        if 'Checksum' in self.attrib:
            del self.attrib['Checksum']

        self.attrib['Checksum'] = self._CalcChecksum()

    @property
    def Checksum(self):
        '''Checksum of the file resource when the node was last updated'''
        checksum = self.attrib.get('Checksum', None)
        if checksum is None:
            checksum = self._CalcChecksum()
            self.attrib['Checksum'] = checksum
            return checksum

        return checksum

    @Checksum.setter
    def Checksum(self, val):
        '''Checksum of the file resource when the node was last updated'''
        self.attrib['Checksum'] = val
        raise DeprecationWarning("Checksums for mosaic elements will not be directly settable soon.  Use ResetChecksum instead")

    def IsValid(self):
        
        result = super(MosaicBaseNode, self).IsValid()
        
        if result[0]:
            knownChecksum = self.attrib.get('Checksum', None)
            if not knownChecksum is None:
                fileChecksum = self._CalcChecksum()
    
                if not knownChecksum == fileChecksum:
                    return [False, "File checksum does not match meta-data"]

        return result 

    def __init__(self, tag, Name, Type, Path=None, attrib=None, **extra):

        if Path is None:
            Path = MosaicBaseNode.GetFilename(Name, Type)

        super(MosaicBaseNode, self).__init__(tag=tag, Path=Path, attrib=attrib, **extra)
        self.attrib['Name'] = Name
        self.attrib['Type'] = Type


    @property
    def InputTransformName(self):
        return self.get('InputTransformName', '')

    @InputTransformName.setter
    def InputTransformName(self, Value):
        self.attrib['InputTransformName'] = Value

    @property
    def InputImageDir(self):
        return self.get('InputTransform', '')

    @InputImageDir.setter
    def InputImageDir(self, Value):
        self.attrib['InputImageDir'] = Value

    @property
    def InputTransformChecksum(self):
        return self.get('InputTransformChecksum', '')

    @InputTransformChecksum.setter
    def InputTransformChecksum(self, Value):
        self.attrib['InputTransformChecksum'] = Value

    @property
    def Type(self):
        return self.attrib.get('Type', '')

    @Type.setter
    def Type(self, Value):
        self.attrib['Type'] = Value


class TransformNode(VMH.InputTransformHandler, MosaicBaseNode):

    @classmethod
    def get_threshold_format(cls):
        return "%2.4g"
    
    @classmethod
    def get_threshold_precision(cls):
        return 2  # Number of digits to save in XML file
    
    def __init__(self, Name, Type, Path=None, attrib=None, **extra):
        super(TransformNode, self).__init__(tag='Transform', Name=Name, Type=Type, Path=Path, attrib=attrib, **extra)
        
    @property
    def ControlSectionNumber(self):
        if 'ControlSectionNumber' in self.attrib:
            return int(self.attrib['ControlSectionNumber'])
        
        return None
    
    @ControlSectionNumber.setter
    def ControlSectionNumber(self, value):
        
        if value is None:
            if 'ControlSectionNumber' in self.attrib:
                del self.attrib['ControlSectionNumber']
        else:
            self.attrib['ControlSectionNumber'] = "%d" % value
        return None
    
    @property
    def MappedSectionNumber(self):
        if 'MappedSectionNumber' in self.attrib:
            return int(self.attrib['MappedSectionNumber'])
        
        return None
    
    @MappedSectionNumber.setter
    def MappedSectionNumber(self, value):
        if value is None:
            if 'MappedSectionNumber' in self.attrib:
                del self.attrib['MappedSectionNumber']
        else:
            self.attrib['MappedSectionNumber'] = "%d" % value
        return None
         
    @property
    def CropBox(self):
        '''Returns boundaries of transform output if available, otherwise none
           :rtype tuple:
           :return (Xo, Yo, Width, Height):
        '''

        if 'CropBox' in self.attrib:
            return nornir_shared.misc.ListFromAttribute(self.attrib['CropBox'])
        else:
            return None

    def CropBoxDownsampled(self, downsample):
        (Xo, Yo, Width, Height) = self.CropBox
        Xo = Xo // float(downsample)
        Yo = Yo // float(downsample)
        Width = int(math.ceil(Width / float(downsample)))
        Height = int(math.ceil(Height / float(downsample)))

        return (Xo, Yo, Width, Height)

    @CropBox.setter
    def CropBox(self, bounds):
        '''Sets boundaries in fixed space for output from the transform.
        :param bounds tuple:  (Xo, Yo, Width, Height) or (Width, Height)
        '''
        if len(bounds) == 4:
            self.attrib['CropBox'] = "%g,%g,%g,%g" % bounds
        elif len(bounds) == 2:
            self.attrib['CropBox'] = "0,0,%g,%g" % bounds
        elif bounds is None:
            if 'CropBox' in self.attrib:
                del self.attrib['CropBox']
        else:
            raise Exception("Invalid argument passed to TransformNode.CropBox %s.  Expected 2 or 4 element tuple." % str(bounds))

    def IsValid(self):
        '''Check if the transform is valid.  Be careful using this, because it only checks the existing meta-data. 
           If you are comparing to a new input transform you should use VMH.IsInputTransformMatched'''
        
        result = super(MosaicBaseNode, self).IsValid()
        if result[0]: 
            [valid, reason] = VMH.InputTransformHandler.InputTransformIsValid(self)
            if valid:
                [valid, reason] = super(TransformNode, self).IsValid()
                
                if not os.path.exists(self.FullPath):
                    self.Locked = False
            
            return [valid, reason]
        else:
            return result
         
    @property
    def Threshold(self):
        val = self.attrib.get('Threshold', None)
        if isinstance(val, str):
            if len(val) == 0:
                return None

        if not val is None:
            val = float(val)

        return val 
    
    @Threshold.setter
    def Threshold(self, val):
        if val is None and 'Threshold' in self.attrib:
            del self.attrib['Threshold']
        
        self.attrib['Threshold'] = TransformNode.get_threshold_format() % val
        

class ImageSetBaseNode(VMH.InputTransformHandler, VMH.PyramidLevelHandler, XContainerElementWrapper):

    def __init__(self, Type, Path, attrib=None, **extra):
        super(ImageSetBaseNode, self).__init__(tag='ImageSet', path=Path, attrib=attrib, **extra)
        self.attrib['Type'] = Type
        self.attrib['Path'] = Path
        
    @property
    def Images(self):
        '''Iterate over images in the ImageSet, highest to lowest res'''
        for levelNode in self.Levels:
            image = levelNode.find('Image')
            if image is None:
                continue
            yield image
            
        return 

    def GetImage(self, Downsample):
        '''Returns image node for the specified downsample or None'''
        
        if not isinstance(Downsample, LevelNode):
            levelNode = self.GetLevel(Downsample)
        else:
            levelNode = Downsample 
            
        if levelNode is None:
            return None

        image = levelNode.find('Image')
        if image is None:
            return None 
        
        if not os.path.exists(image.FullPath):
            if image in self:
                self.remove(image)

            return None

        return image
    
    def HasImage(self, Downsample):
        return not self.GetImage(Downsample) is None

    def GetOrCreateImage(self, Downsample, Path=None, GenerateData=True):
        '''Returns image node for the specified downsample. Generates image if requested and image is missing.  If unable to generate an image node is returned'''
        [added_level, LevelNode] = self.GetOrCreateLevel(Downsample, GenerateData=False)

        imageNode = LevelNode.find("Image")
        if imageNode is None:
            
            if GenerateData and not self.CanGenerate(Downsample):
                raise ValueError("%s Cannot generate downsample %d" % (self.FullPath, Downsample))
            
            if Path is None:
                Path = self.__PredictImageFilename()

            imageNode = ImageNode(Path)
            [level_added, imageNode] = LevelNode.UpdateOrAddChild(imageNode)
            if not os.path.exists(imageNode.FullPath):
                if not os.path.exists(os.path.dirname(imageNode.FullPath)):
                    os.makedirs(os.path.dirname(imageNode.FullPath))
                
                if GenerateData:
                    self.__GenerateMissingImageLevel(OutputImage=imageNode, Downsample=Downsample)
            
            self.Save()
                    
        return imageNode
    
    
    def __PredictImageFilename(self):
        '''Get the path of the highest resolution image in this ImageSet'''
        list_images = list(self.Images)
        if len(list_images) > 0:
            return list_images[0].Path
        
        raise LookupError("No images found to predict path in imageset %s" % self.FullPath)
    
    
    def GetOrPredictImageFullPath(self, Downsample):
        '''Either return what the full path to the image at the downsample is, or predict what it should be if it does not exist without creating it
        :rtype str:
        '''
        image_node = self.GetImage(Downsample)
        if image_node is None:
            return os.path.join(self.FullPath, LevelNode.PredictPath(Downsample) , self.__PredictImageFilename())
        else:
            return image_node.FullPath
        

    def __GetImageNearestToLevel(self, Downsample):
        '''Returns the nearest existing image and downsample level lower than the requested downsample level'''

        SourceImage = None
        SourceDownsample = Downsample / 2
        while SourceDownsample > 0:
            SourceImage = self.GetImage(SourceDownsample)
            if not SourceImage is None:

                # Only return images that actually are on disk
                if os.path.exists(SourceImage.FullPath):
                    break
                else:
                    # Probably a bad node, remove it
                    self.CleanIfInvalid()

            SourceDownsample = SourceDownsample / 2.0

        return (SourceImage, SourceDownsample)

    def GenerateLevels(self, Levels):
        node = tile.BuildImagePyramid(self, Levels, Interlace=False)
        if not node is None:
            node.Save()

    def __GenerateMissingImageLevel(self, OutputImage, Downsample):
        '''Creates a downsampled image from available high-res images if needed'''

        (SourceImage, SourceDownsample) = self.__GetImageNearestToLevel(Downsample)

        if SourceImage is None:
            # raise Exception("No source image available to generate missing downsample level: " + OutputImage)
            return None

        OutputImage.Path = SourceImage.Path
        if 'InputImageChecksum' in SourceImage.attrib:
            OutputImage.InputImageChecksum = SourceImage.InputImageChecksum

        ShrinkP = nornir_shared.images.Shrink(SourceImage.FullPath, OutputImage.FullPath, float(Downsample) / float(SourceDownsample))
        ShrinkP.wait()
        
        return OutputImage

    def IsValid(self):
        [valid, reason] = VMH.InputTransformHandler.InputTransformIsValid(self)
        if valid:
            return super(ImageSetBaseNode, self).IsValid()
        else:
            return [valid, reason]
        
    @property
    def Checksum(self):
        raise NotImplementedError("Checksum on ImageSet... not sure why this would be needed.  Try using checksum of highest resolution image instead?")


class ImageSetNode(ImageSetBaseNode):
 
    DefaultPath = 'Images'
    
    
    def FindDownsampleForSize(self, requested_size):
        '''Find the smallest existing image of the requested size or greater.  If it does not exist return the maximum resolution level
        :param tuple requested_size: Either a tuple or integer.  A tuple requires both dimensions to be larger than the requested_size.  A integer requires only one of the dimensions to be larger.
        :return: Downsample level
        '''
        
        level = self.MinResLevel 
        while(level > self.MaxResLevel):
            dim = self.GetImage(level).Dimensions
            if isinstance(requested_size, tuple):
                if dim[0] >= requested_size[0] and dim[1] >= requested_size[1]:
                    return level.Downsample
            elif dim[0] >= requested_size or dim[1] >= requested_size:
                    return level.Downsample
                
            level = self.MoreDetailedLevel(level.Downsample)
            
        return self.MaxResLevel.Downsample
    
    def IsLevelPopulated(self, level_full_path):
        '''
        :param str level_full_path: The path to the directories containing the image files
        :return: (Bool, String) containing whether all tiles exist and a reason string
        '''
    
        globfullpath = os.path.join(level_full_path, '*' + self.ImageFormatExt)

        files = glob.glob(globfullpath)

        if(len(files) == 0):
            return [False, "No files in level"]

        FileNumberMatch = len(files) <= self.NumberOfTiles

        if not FileNumberMatch:
            return [False, "File count mismatch for level"] 
        
        return [True, None]

        
    def __init__(self, Type=None, attrib=None, **extra):

        if Type is None:
            Type = ""

        # if Path is None:
        #    Path = ImageSetNode.Name + Type

        super(ImageSetNode, self).__init__(Type=Type, Path=ImageSetNode.DefaultPath, attrib=attrib, **extra)


class ImageNode(VMH.InputTransformHandler, XFileElementWrapper):

    DefaultName = "image.png"

    def __init__(self, Path, attrib=None, **extra):

        super(ImageNode, self).__init__(tag='Image', Path=Path, attrib=attrib, **extra)


    def IsValid(self):
        if not os.path.exists(self.FullPath):
            return [False, 'File does not exist']

        if(self.Checksum != nornir_shared.checksum.FilesizeChecksum(self.FullPath)):
            return [False, "Checksum mismatch"]

        return super(ImageNode, self).IsValid()


    @property
    def Checksum(self):
        checksum = self.get('Checksum', None)
        if checksum is None:
            checksum = nornir_shared.checksum.FilesizeChecksum(self.FullPath)
            self.attrib['Checksum'] = str(checksum)

        return checksum
    
    @property
    def Dimensions(self):
        ''':return: (height, width)'''
        return nornir_imageregistration.GetImageSize(self.FullPath)


class DataNode(XFileElementWrapper):
    '''Refers to an external file containing data'''
    def __init__(self, Path, attrib=None, **extra):

        super(DataNode, self).__init__(tag='Data', Path=Path, attrib=attrib, **extra)


class SectionMappingsNode(XElementWrapper):

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return self.tag + ' ' + (nornir_buildmanager.templates.Current.SectionTemplate % self.MappedSectionNumber)

    @property
    def MappedSectionNumber(self):
        return int(self.attrib['MappedSectionNumber'])

    @property
    def Transforms(self):
        return list(self.findall('Transform'))

    @property
    def Images(self):
        return list(self.findall('Image'))

    def TransformsToSection(self, sectionNumber):
        return self.GetChildrenByAttrib('Transform', 'ControlSectionNumber', sectionNumber)

    def FindStosTransform(self, ControlSectionNumber, ControlChannelName, ControlFilterName, MappedSectionNumber, MappedChannelName, MappedFilterName):
        '''
        Find the stos transform matching all of the parameters if it exists
        WORKAROUND: The etree implementation has a serious shortcoming in that it cannot handle the 'and' operator in XPath queries.  This function is a workaround for a multiple criteria find query
        :rtype TransformNode:
        '''
        
        # TODO: 3/10/2017 I believe I can stop checking MappedSectionNumber because it is built into the SectionMapping node.  This is a sanity check before I pull the plug
        assert(MappedSectionNumber == self.MappedSectionNumber)
        
        for t in self.Transforms:
            if int(t.ControlSectionNumber) != int(ControlSectionNumber):
                continue

            if t.ControlChannelName != ControlChannelName:
                continue

            if t.ControlFilterName != ControlFilterName:
                continue

            if int(t.MappedSectionNumber) != int(MappedSectionNumber):
                continue

            if t.MappedChannelName != MappedChannelName:
                continue

            if t.MappedFilterName != MappedFilterName:
                continue

            return t

        return None
     
    def TryRemoveTransformNode(self, transform_node):
        '''Remove the transform if it exists
        :rtype bool:
        :return: True if transform removed 
        '''
        return self.TryRemoveTransform(transform_node.ControlSectionNumber,
                                    transform_node.ControlChannelName,
                                    transform_node.ControlFilterName,
                                    transform_node.MappedChannelName,
                                    transform_node.MappedFilterName)
    
    def TryRemoveTransform(self, ControlSectionNumber, ControlChannelName, ControlFilterName, MappedChannelName, MappedFilterName):
        '''Remove the transform if it exists
        :rtype bool:
        :return: True if transform removed 
        '''
        
        existing_transform = self.FindStosTransform(ControlSectionNumber, ControlChannelName, ControlFilterName, self.MappedSectionNumber, MappedChannelName, MappedFilterName)
        if not existing_transform is None:
            existing_transform.Clean()
            return True
        
        return False
        
    
    def AddOrUpdateTransform(self, transform_node):
        '''
        Add or update a transform to the section mappings.
        :rtype bool:
        :return: True if the transform node was added.  False if updated.
        '''
        existing_transform = self.TryRemoveTransformNode(transform_node) 
        self.AddChild(transform_node)
        return not existing_transform
            

    @classmethod
    def _CheckForFilterExistence(self, block, section_number, channel_name, filter_name):

        section_node = block.GetSection(section_number)
        if section_node is None:
            return (False, "Transform section not found %d.%s.%s" % (section_number, channel_name, filter_name))

        channel_node = section_node.GetChannel(channel_name)
        if channel_node is None:
            return (False, "Transform channel not found %d.%s.%s" % (section_number, channel_name, filter_name))

        filter_node = channel_node.GetFilter(filter_name)
        if filter_node is None:
            return (False, "Transform filter not found %d.%s.%s" % (section_number, channel_name, filter_name))

        return (True, None)


    def CleanIfInvalid(self):
        cleaned = XElementWrapper.CleanIfInvalid(self)
        if not cleaned:
            return self.CleanTransformsIfInvalid()
        
        return cleaned
        

    def CleanTransformsIfInvalid(self):
        block = self.FindParent('Block')
        
        transformCleaned = False;

        # Check the transforms and make sure the input data still exists
        for t in self.Transforms:
            transformValid = t.IsValid()
            if not transformValid[0]:
                prettyoutput.Log("Cleaning invalid transform " + t.Path + " " + transformValid[1])
                t.Clean();
                transformCleaned = True;
                continue;
            
            ControlResult = SectionMappingsNode._CheckForFilterExistence(block, t.ControlSectionNumber, t.ControlChannelName, t.ControlFilterName)
            if ControlResult[0] == False:
                prettyoutput.Log("Cleaning transform " + t.Path + " control input did not exist: " + ControlResult[1])
                t.Clean()
                transformCleaned = True;
                continue

            MappedResult = SectionMappingsNode._CheckForFilterExistence(block, t.MappedSectionNumber, t.MappedChannelName, t.MappedFilterName)
            if MappedResult[0] == False:
                prettyoutput.Log("Cleaning transform " + t.Path + " mapped input did not exist: " + MappedResult[1])
                t.Clean()
                transformCleaned = True;
                continue
            
        return transformCleaned


    def __init__(self, MappedSectionNumber=None, attrib=None, **extra):
        super(SectionMappingsNode, self).__init__(tag='SectionMappings', attrib=attrib, **extra)

        if not MappedSectionNumber is None:
            self.attrib['MappedSectionNumber'] = str(MappedSectionNumber)


class TilePyramidNode(XContainerElementWrapper, VMH.PyramidLevelHandler):

    DefaultName = 'TilePyramid'
    DefaultPath = 'TilePyramid'

    @property
    def LevelFormat(self):
        return self.attrib['LevelFormat']

    @LevelFormat.setter
    def LevelFormat(self, val):
        assert(isinstance(val, str))
        self.attrib['LevelFormat'] = val

    @property
    def NumberOfTiles(self):
        return int(self.attrib.get('NumberOfTiles', 0))

    @NumberOfTiles.setter
    def NumberOfTiles(self, val):
        self.attrib['NumberOfTiles'] = '%d' % val

    @property
    def ImageFormatExt(self):
        return self.attrib['ImageFormatExt']

    @ImageFormatExt.setter
    def ImageFormatExt(self, val):
        assert(isinstance(val, str))
        self.attrib['ImageFormatExt'] = val
        
    @property
    def Type(self):
        '''The default mask to use for this filter'''
        m = self.attrib.get("Type", None)
        if not m is None:
            if len(m) == 0:
                m = None

        return m

    @Type.setter
    def Type(self, val):
        if val is None:
            if 'Type' in self.attrib:
                del self.attrib['Type']
        else:
            self.attrib['Type'] = val

    def IsLevelPopulated(self, level_full_path):
        '''
        :param str level_full_path: The path to the directories containing the image files
        :return: (Bool, String) containing whether all tiles exist and a reason string
        '''
    
        globfullpath = os.path.join(level_full_path, '*' + self.ImageFormatExt)

        files = glob.glob(globfullpath)

        if(len(files) == 0):
            return [False, "No files in level"]

        FileNumberMatch = len(files) <= self.NumberOfTiles

        if not FileNumberMatch:
            return [False, "File count mismatch for level"] 
        
        return [True, None]


    def __init__(self, NumberOfTiles=0, LevelFormat=None, ImageFormatExt=None, attrib=None, **extra):

        if LevelFormat is None:
            LevelFormat = nornir_buildmanager.templates.Current.LevelFormat

        if ImageFormatExt is None:
            ImageFormatExt = '.png'

        super(TilePyramidNode, self).__init__(tag='TilePyramid',
                                               path=TilePyramidNode.DefaultPath,
                                               attrib=attrib, **extra)

        self.attrib['NumberOfTiles'] = str(NumberOfTiles)
        self.attrib['LevelFormat'] = LevelFormat
        self.attrib['ImageFormatExt'] = ImageFormatExt

    def GenerateLevels(self, Levels):
        node = tile.BuildTilePyramids(self, Levels)
        if not node is None:
            node.Save()

class TilesetNode(XContainerElementWrapper, VMH.PyramidLevelHandler):

    DefaultPath = 'Tileset'

    @property
    def CoordFormat(self):
        return self.attrib['CoordFormat']

    @CoordFormat.setter
    def CoordFormat(self, val):
        self.attrib['CoordFormat'] = val

    @property
    def FilePrefix(self):
        return self.attrib['FilePrefix']

    @FilePrefix.setter
    def FilePrefix(self, val):
        self.attrib['FilePrefix'] = val

    @property
    def FilePostfix(self):
        return self.attrib['FilePostfix']

    @FilePostfix.setter
    def FilePostfix(self, val):
        self.attrib['FilePostfix'] = val

    @property
    def TileXDim(self):
        return int(self.attrib['TileXDim'])

    @TileXDim.setter
    def TileXDim(self, val):
        self.attrib['TileXDim'] = '%d' % int(val)

    @property
    def TileYDim(self):
        return int(self.attrib['TileYDim'])

    @TileYDim.setter
    def TileYDim(self, val):
        self.attrib['TileYDim'] = '%d' % int(val)

    @property
    def GridDimX(self):
        return int(self.attrib['GridDimX'])

    @GridDimX.setter
    def GridDimX(self, val):
        self.attrib['GridDimX'] = '%d' % int(val)

    @property
    def GridDimY(self):
        return int(self.attrib['GridDimY'])

    @GridDimY.setter
    def GridDimY(self, val):
        self.attrib['GridDimY'] = '%d' % int(val)

    def __init__(self, attrib=None, **extra):
        super(TilesetNode, self).__init__(tag='Tileset', path=TilesetNode.DefaultPath, attrib=attrib, **extra)
 
        if(not 'Path' in self.attrib):
            self.attrib['Path'] = TilesetNode.DefaultPath

    def GenerateLevels(self, Levels):
        node = tile.BuildTilesetPyramid(self)
        if not node is None:
            node.Save()

    def IsLevelPopulated(self, level_full_path, GridDimX, GridDimY):
        '''
        :param str level_full_path: The path to the directories containing the image files
        :return: (Bool, String) containing whether all tiles exist and a reason string
        '''

        FilePrefix = self.FilePrefix
        FilePostfix = self.FilePostfix
        GridXDim = int(GridDimX) - 1
        GridYDim = int(GridDimY) - 1

        GridXString = nornir_buildmanager.templates.Current.GridTileCoordTemplate % GridXDim
        # MatchString = os.path.join(OutputDir, FilePrefix + 'X%' + nornir_buildmanager.templates.GridTileCoordFormat % GridXDim + '_Y*' + FilePostfix)
        MatchString = os.path.join(level_full_path, nornir_buildmanager.templates.Current.GridTileMatchStringTemplate % {'prefix' :FilePrefix,
                                                                                    'X' :  GridXString,
                                                                                    'Y' : '*',
                                                                                    'postfix' :  FilePostfix})

        # Start with the middle because it is more likely to have a match earlier
        TestIndicies = range(GridYDim / 2, GridYDim)
        TestIndicies.extend(range((GridYDim / 2) - 1, -1, -1))
        for iY in TestIndicies:
            # MatchString = os.path.join(OutputDir, FilePrefix +
            #                           'X' + nornir_buildmanager.templates.GridTileCoordFormat % GridXDim +
            #                           '_Y' + nornir_buildmanager.templates.GridTileCoordFormat % iY +
            #                           FilePostfix)
            MatchString = os.path.join(level_full_path, nornir_buildmanager.templates.Current.GridTileMatchStringTemplate % {'prefix' :  FilePrefix,
                                                                                    'X' : GridXString,
                                                                                    'Y' : nornir_buildmanager.templates.Current.GridTileCoordTemplate % iY,
                                                                                    'postfix' : FilePostfix})
            if(os.path.exists(MatchString)):
                return [True, "Last column of tileset found"]

            MatchString = os.path.join(level_full_path, nornir_buildmanager.templates.Current.GridTileNameTemplate % {'prefix' :  FilePrefix,
                                                                                    'X' : GridXDim,
                                                                                    'Y' : iY,
                                                                                    'postfix' : FilePostfix})
            if(os.path.exists(MatchString)):
                return [True, "Last column of tileset found"]

        return [False, "Last column of tileset not found"]


class LevelNode(XContainerElementWrapper):

    @classmethod
    def PredictPath(cls, level):
        return nornir_buildmanager.templates.Current.LevelFormat % int(level)
        
    @classmethod
    def ClassSortKey(cls, self):
        '''Required for objects derived from XContainerElementWrapper'''
        return "Level" + ' ' + nornir_buildmanager.templates.Current.DownsampleFormat % float(self.Downsample)

    @property
    def SortKey(self):
        '''The default key used for sorting elements'''
        return LevelNode.ClassSortKey(self)

    @property
    def Name(self):
        return '%g' % self.Downsample

    @Name.setter
    def Name(self, Value):
        assert False  # , "Attempting to set name on LevelNode")

    @property
    def Downsample(self):
        assert('Downsample' in self.attrib)
        return float(self.attrib.get('Downsample', ''))

    @Downsample.setter
    def Downsample(self, Value):
        self.attrib['Downsample'] = '%g' % Value
              

    def IsValid(self):
        '''Remove level directories without files, or with more files than they should have'''

        if not os.path.isdir(self.FullPath):
            return [False, 'Directory does not exist']
         
        PyramidNode = self.Parent
        if(isinstance(PyramidNode, TilePyramidNode)):
            return PyramidNode.IsLevelPopulated(self.FullPath)
        elif(isinstance(PyramidNode, TilesetNode)):
            return PyramidNode.IsLevelPopulated(self.FullPath, self.GridDimX, self.GridDimY)
        elif(isinstance(PyramidNode, ImageSetNode)):
            if not PyramidNode.HasImage(self.Downsample):
                return (False, "No image node found")
            # Make sure each level has at least one tile from the last column on the disk.
            
        return (True, None)


    def __init__(self, Level, attrib=None, **extra):

        if(attrib is None):
            attrib = {}

        if isinstance(Level, str):
            attrib['Downsample'] = Level
        else:
            attrib['Downsample'] = '%g' % Level

        super(LevelNode, self).__init__(tag='Level', path=LevelNode.PredictPath(Level), attrib=attrib, **extra)


class HistogramBase(VMH.InputTransformHandler, XElementWrapper):

    @property
    def DataNode(self):
        return self.find('Data')

    @property
    def ImageNode(self):
        return self.find('Image')

    @property
    def DataFullPath(self):
        if self.DataNode is None:
            return ""

        return self.DataNode.FullPath

    @property
    def ImageFullPath(self):
        if self.ImageNode is None:
            return ""

        return self.ImageNode.FullPath

    @property
    def Checksum(self):
        if(self.DataNode is None):
            return ""
        else:
            return self.DataNode.Checksum

    def IsValid(self):
        '''Remove this node if our output does not exist'''
        if self.DataNode is None:
            return [False, "No data node found"]
        else:
            if not os.path.exists(self.DataNode.FullPath):
                return [False, "No file to match data node"]

        '''Check for the transform node and ensure the checksums match'''
        # TransformNode = self.Parent.find('Transform')

        return super(HistogramBase, self).IsValid()

    def __init__(self, tag, attrib, **extra):
        super(HistogramBase, self).__init__(tag=tag, attrib=attrib, **extra)


class AutoLevelHintNode(XElementWrapper):

    @property
    def UserRequestedMinIntensityCutoff(self):
        '''Returns None or a float'''
        val = self.attrib.get('UserRequestedMinIntensityCutoff', None)
        if val is None or  len(val) == 0:
            return None
        return float(val)

    @UserRequestedMinIntensityCutoff.setter
    def UserRequestedMinIntensityCutoff(self, val):
        if val is None:
            self.attrib['UserRequestedMinIntensityCutoff'] = ""
        else:
            if math.isnan(val):
                self.attrib['UserRequestedMinIntensityCutoff'] = ""
            else:
                self.attrib['UserRequestedMinIntensityCutoff'] = "%g" % val

    @property
    def UserRequestedMaxIntensityCutoff(self):
        '''Returns None or a float'''
        val = self.attrib.get('UserRequestedMaxIntensityCutoff', None)
        if val is None or len(val) == 0:
            return None
        return float(val)

    @UserRequestedMaxIntensityCutoff.setter
    def UserRequestedMaxIntensityCutoff(self, val):
        if val is None:
            self.attrib['UserRequestedMaxIntensityCutoff'] = ""
        else:
            if math.isnan(val):
                self.attrib['UserRequestedMaxIntensityCutoff'] = ""
            else:
                self.attrib['UserRequestedMaxIntensityCutoff'] = "%g" % val

    @property
    def UserRequestedGamma(self):
        '''Returns None or a float'''
        val = self.attrib.get('UserRequestedGamma', None)
        if val is None or len(val) == 0:
            return None
        return float(val)

    @UserRequestedGamma.setter
    def UserRequestedGamma(self, val):
        if val is None:
            self.attrib['UserRequestedGamma'] = ""
        else:
            if math.isnan(val):
                self.attrib['UserRequestedGamma'] = ""
            else:
                self.attrib['UserRequestedGamma'] = "%g" % val

    def __init__(self, MinIntensityCutoff=None, MaxIntensityCutoff=None):
        attrib = {'UserRequestedMinIntensityCutoff' : "",
                  'UserRequestedMaxIntensityCutoff' : "",
                  'UserRequestedGamma' : ""}
        super(AutoLevelHintNode, self).__init__(tag='AutoLevelHint', attrib=attrib)


class HistogramNode(HistogramBase):

    def __init__(self, InputTransformNode, Type, attrib, **extra):
        super(HistogramNode, self).__init__(tag='Histogram', attrib=attrib, **extra)
        self.SetTransform(InputTransformNode)
        self.attrib['Type'] = Type

    def GetAutoLevelHint(self):
        return self.find('AutoLevelHint')

    def GetOrCreateAutoLevelHint(self):
        if not self.GetAutoLevelHint() is None:
            return self.GetAutoLevelHint()
        else:
            # Create a new AutoLevelData node using the calculated values as overrides so users can find and edit it later
            self.UpdateOrAddChild(AutoLevelHintNode())
            return self.GetAutoLevelHint()

class PruneNode(HistogramBase):

    @property
    def Overlap(self):
        return float(self.attrib['Overlap'])

    @property
    def UserRequestedCutoff(self):
        val = self.attrib.get('UserRequestedCutoff', None)
        if isinstance(val, str):
            if len(val) == 0:
                return None

        if not val is None:
            val = float(val)

        return val

    @UserRequestedCutoff.setter
    def UserRequestedCutoff(self, val):
        if val is None:
            val = ""

        self.attrib['UserRequestedCutoff'] = str(val)

    def __init__(self, Type, Overlap, attrib=None, **extra):
        super(PruneNode, self).__init__(tag='Prune', attrib=attrib, **extra)
        self.attrib['Type'] = Type
        self.attrib['Overlap'] = str(Overlap)

        if not 'UserRequestedCutoff' in self.attrib:
            self.attrib['UserRequestedCutoff'] = ""

if __name__ == '__main__':
    VolumeManager.Load("C:\Temp")

    tagdict = XPropertiesElementWrapper.wrap(ElementTree.Element("Tag"))
    tagdict.V = 5
    tagdict.Path = "path"

    tagdict.Value = 34.56

    tagdict.Value = 43.7

    print(ElementTree.tostring(tagdict))

    del tagdict.Value
    del tagdict.Path

    print(ElementTree.tostring(tagdict))
 
    tagdict = XElementWrapper.wrap(ElementTree.Element("Tag"))
    tagdict.V = 5
    tagdict.Path = "path"

    tagdict.Value = 34.56

    tagdict.Value = 43.7

    print(ElementTree.tostring(tagdict))

    del tagdict.Value
    del tagdict.Path

    print(ElementTree.tostring(tagdict))

    tagdict = XContainerElementWrapper.wrap(ElementTree.Element("Tag"))
    tagdict.V = 5
    tagdict.Path = "path"

    tagdict.Value = 34.56

    tagdict.Value = 43.7

    tagdict.Properties.Path = "Path2"
    tagdict.Properties.Value = 75
    tagdict.Properties.Value = 57

    print(ElementTree.tostring(tagdict))

    del tagdict.Value
    del tagdict.Path

    del tagdict.Properties.Value
    del tagdict.Properties.Path

    print(ElementTree.tostring(tagdict))



