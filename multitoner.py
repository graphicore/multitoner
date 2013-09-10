#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import sys
import os
import json
from gi.repository import Gtk, Gdk, GObject
from gtkinktool import InksEditor, ModelCurves, ModelInk, History, GradientWorker
from emitter import Emitter
from compatibility import repair_gsignals

# just a preparation for i18n
def _(string):
    return string

UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action='FileMenu'>
      <menuitem action='FileNew' />
      <separator />
      <menuitem action='FileOpen' />
      <menuitem action='FileOpenRecent' />
      <separator />
      <menuitem action='FileSaveDocument' />
      <menuitem action='FileSaveAsDocument' />
      <menuitem action='FileSaveAll' />
      <separator />
      <menuitem action='FileClose' />
      <menuitem action='FileCloseOther' />
      <menuitem action='FileCloseAll' />
      <separator />
      <menuitem action='FileQuit' />
    </menu>
    <menu action='EditMenu'>
      <menuitem action='EditUndo' />
      <menuitem action='EditRedo' />
      <separator />
    </menu>
  </menubar>
  
</ui>
"""

class Label(Gtk.Grid):
    __gsignals__ = repair_gsignals({
        'close': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                  # id
                  GObject.TYPE_INT, ))
    })
    def __init__(self, id, text):
        Gtk.Grid.__init__(self)
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_column_spacing(5)
        #self.set_row_spacing(5)
        
        # icon
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_FILE, Gtk.IconSize.MENU)
        self.attach(icon, 0, 0, 1, 1)
        
        # label 
        self.label = label = Gtk.Label(text)
        self.attach_next_to(label, icon, Gtk.PositionType.RIGHT, 1, 1)
        
        # close button
        button = Gtk.Button()
        button.set_focus_on_click(False)
        button.add(Gtk.Image.new_from_stock(Gtk.STOCK_CLOSE, Gtk.IconSize.MENU))
        button.connect('clicked', self.clickedHandler, id)
        self.attach_next_to(button, label, Gtk.PositionType.RIGHT, 1, 1)
        self.show_all()
    def clickedHandler(self, button, id, data=None):
        self.emit("close", id)
    
    def setLabelText(self, text):
        self.label.set_text(text)
    
    def setChangedIndicator(self, hasChanges):
        _class = 'has-changes'
        if hasChanges:
            self.get_style_context().add_class(_class)
        else:
            self.get_style_context().remove_class(_class)

class Document(Emitter):
    fileExtension = '.mtt' # .m(ulti)t(oner)t(ool)
    untitledName = _('untitled')
    def __init__(self, gradientWorker, filename=None, data=None):
        if data is None:
            data = {}
        self._gradientWorker = gradientWorker
        model = ModelCurves(ChildModel=ModelInk, **data)
        model.add(self)
        history = History(model)
        inksEditor = InksEditor(model, self._gradientWorker)
        self.id = id(self)
        label = Label(self.id, self.untitledName)
        
        self.history = history
        self.model = model
        self.widget = inksEditor
        self.label = label
        self.filename = filename
    
    @classmethod
    def newFromFile(Cls, gradientWorker, filename):
        with open(filename, 'r') as f:
            data = json.load(f)
        print ('opened', data)
        return Cls(gradientWorker, filename, data)
    
    @property
    def filename(self):
        return getattr(self, '_filename', None)
    
    def triggerOnDocumentStateUpdate(self, *args):
        for item in self._subscriptions:
            item.onDocumentStateUpdate(self, *args)
    
    @property
    def hasChanges(self):
        return getattr(self, '_hasChanges', False)
    
    @hasChanges.setter
    def hasChanges(self, value):
        old = self.hasChanges
        self._hasChanges = not not value
        if old != self._hasChanges:
            self.label.setChangedIndicator(self._hasChanges)
        self.triggerOnDocumentStateUpdate() 
    
    def onModelUpdated(self, model, event, *args):
        """ 
        model updates are used as indicator that the history changed as well
        """
        self.hasChanges = True
    
    @filename.setter
    def filename(self, value):
        self._filename = value
        if self._filename is None:
            label = self.untitledName
        else:
            label = os.path.basename(self._filename)
        self.label.setLabelText(label)
        self.label.set_tooltip_text(self._filename or '')
    
    def _save(self, filename):
        data = self.model.getArgs()
        print ('_save', data)
        data = json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))
        with open(filename, 'w') as f:
            f.write(data)
        self.hasChanges = False
    
    def save(self):
        self._save(self.filename)
    
    def saveAs(self, filename):
        self._save(filename)
        self.filename = filename

class Multitoner(Gtk.Grid):
    def __init__(self):
        Gtk.Grid.__init__(self)
        self._gradientWorker = GradientWorker()
        self._documents = {}
        self.activeDocument = None
        
        self._documentActions = self._makeDocumentActions()
        self._globalActions = self._makeGlobalActions()
        self.menubar = menubar = self._initMenu()
        self.attach(menubar, 0, 0, 1, 1)
        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        
        self._notebook.connect('switch-page', self.switchPageHandler)
        self._notebook.connect('page-removed' , self.pageAddRemoveHandler)
        self._notebook.connect('page-added'   , self.pageAddRemoveHandler)
        
        self.attach(self._notebook, 0, 1, 1, 1)
        self._setActiveDocumentState()
        self._setGlobalState()
    
    def switchPageHandler(self, widget, page, page_num):
        self.setCurrentPage(page_num)
    
    def pageAddRemoveHandler(self, *data):
        self.setCurrentPage()
    
    def getDocumentByPage(self, page):
        widget = self._notebook.get_nth_page(page)
        return self.getDocumentByWidget(widget)
    
    def getDocumentByWidget(self, widget):
        for doc in self._documents.values():
            if doc.widget is widget:
                return doc
        return None
    
    def getDocumentByFileName(self, filename):
        for doc in self._documents.values():
            if doc.filename == filename:
                return doc
        return None
    
    @property
    def hasChangedDocuments(self):
        for doc in self._documents.values():
            if doc.hasChanges:
                return True
        return False
    
    def setActivePage(self, doc):
        page = self._notebook.page_num(doc.widget)
        self._notebook.set_current_page(page)
    
    def onDocumentStateUpdate(self, doc, *args):
        if doc is self.activeDocument:
            self._setActiveDocumentState()
        self._setGlobalState()
    
    def setCurrentPage(self, page=None):
        if page is None:
            page = self._notebook.get_current_page()
        # activeDocument is either a Document or None
        self.activeDocument = self.getDocumentByPage(page)
        self._setActiveDocumentState()
        self._setGlobalState()
    
    def _setGlobalState(self):
        actions = (
              ('FileSaveAll', self.hasChangedDocuments)
            , ('FileCloseAll', len(self._documents) > 0)
        )
        self._actionsSetSensitive(self._globalActions, *actions)
    
    def _setActiveDocumentState(self):
        if self.activeDocument is None:
            # there is no current page
            self._documentActions.set_sensitive(False)
            return
        else:
            self._documentActions.set_sensitive(True)
        
        undos, redos = self.activeDocument.history.getCounts()
        actions = (
              ('FileSaveDocument', self.activeDocument.hasChanges)
            , ('EditUndo', undos > 0)
            , ('EditRedo', redos > 0)
            , ('FileCloseOther', len(self._documents) > 1)
            
        )
        self._actionsSetSensitive(self._documentActions, *actions)
    
    def _actionsSetSensitive(self, actionGroup, *actionTuples):
        for actionName, sensitive in actionTuples:
            action = actionGroup.get_action(actionName)
            action.set_sensitive(sensitive)
    
    def _initMenu(self):
        self.UIManager = uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._globalActions)
        uimanager.insert_action_group(self._documentActions)
        menubar = uimanager.get_widget("/MenuBar")
        
        #toolbar = uimanager.get_widget("/ToolBar")
        # this removes the immediate dependency to window
        def onRealize(widget, *args):
            """ 
            closure to connect to window when it establishes this widget
            """
            window = widget.get_toplevel()
            # Add the accelerator group to the toplevel window
            accelgroup = uimanager.get_accel_group()
            window.add_accel_group(accelgroup)
            # connect just once ever
            widget.disconnect(realize_handler_id)
        #save realize_handler_id for the closure of onRealize 
        realize_handler_id = self.connect('realize' , onRealize)
        return menubar
    
    def openRecentHandler(self, widget):
        item = widget.get_current_item()
        uri = item.get_uri()
        if uri.startswith('file://'):
            filename = uri[(len('file://')):]
            self.openDocument(filename)
    
    def _makeGlobalActions(self):
        actionGroup = Gtk.ActionGroup('global_actions')
        actionGroup.add_actions([
              ('FileMenu', None, _('File'), None,
               None, None)
            , ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('FileNew', Gtk.STOCK_NEW, _('New'), '<Ctrl>n',
               _('Start a new document.'), self.menuFileNewHandler)
            , ('FileQuit', Gtk.STOCK_QUIT, _('Quit'), '<ctrl>q',
               None, self.menuFileQuitHandler)
            , ('FileOpen', Gtk.STOCK_OPEN, _('Open'), '<Ctrl>o',
               _('Open a document.'), self.menuFileOpenHandler)
            , ('FileSaveAll', Gtk.STOCK_SAVE, _('Save All'), '<Ctrl><Shift>s',
               _('Save all documents.'), self.menuFileSaveAllHandler)
            , ('FileCloseAll', Gtk.STOCK_CLOSE, _('Close All'), '<Ctrl><Shift>w',
               _('Close all documents.'), self.menuFileCloseAllHandler)
            ])
        # recent files chooser
        # does only .mtt files
        recentAction = Gtk.RecentAction.new_for_manager('FileOpenRecent',
            _('Recent Files'), None, None, None)
        recentFilter= Gtk.RecentFilter()
        recentFilter.add_pattern ("*" + Document.fileExtension);
        recentAction.add_filter(recentFilter)
        recentAction.connect('item-activated', self.openRecentHandler)
        actionGroup.add_action(recentAction)
        return actionGroup
    
    def _makeDocumentActions(self):
        actionGroup = Gtk.ActionGroup('document_actions')
        actionGroup.add_actions([
              ('EditUndo', Gtk.STOCK_UNDO, _('Undo'),  '<Ctrl>z',
               None, self.menuEditUndoHandler)
            , ('EditRedo', Gtk.STOCK_REDO, _('Redo'), '<Ctrl>y',
               None, self.menuEditRedoHandler)
            , ('FileSaveDocument', Gtk.STOCK_SAVE, _('Save'), '<ctrl>s',
               None, self.menuFileSaveDocumentHandler)
            , ('FileSaveAsDocument', Gtk.STOCK_SAVE, _('Save As'), '<ctrl><alt>s',
               None, self.menuFileSaveDocumentAsHandler)
            , ('FileClose', Gtk.STOCK_CLOSE, _('Close'), '<ctrl>w',
               None, self.menuFileCloseHandler)
            , ('FileCloseOther', Gtk.STOCK_CLOSE, _('Close Other Documents'), '<ctrl><alt>w',
               None, self.menuFileCloseOtherHandler)
            ])
        
        actionGroup.set_sensitive(False)
        return actionGroup
    
    def _registerDocument(self, doc):
        self._documents[doc.id] = doc
        doc.label.connect('close', self.closeDocumentHandler, doc.id)
        doc.add(self)
        page = self._notebook.append_page(doc.widget, doc.label)
        self._notebook.set_tab_reorderable(doc.widget, True)
        doc.widget.show_all()
        self._notebook.set_current_page(page)
        return doc.id
    
    def _unregisterDocument(self, doc):
        doc.remove(self)
        del self._documents[doc.id]
        page = self._notebook.page_num(doc.widget)
        self._notebook.remove_page(page)
    
    def makeNewDocument(self):
        doc = Document(self._gradientWorker)
        self._registerDocument(doc)
    
    def _openDocument(self, filename):
        try:
            doc = Document.newFromFile(self._gradientWorker, filename)
        except Exception as e:
            error = 'Error opening the file "{0}"'.format(filename)
            detail = '{1} {0}'.format(type(e), e)
            self._announceError(error, detail)
        else:
            self._registerDocument(doc)
    
    def openDocument(self, filename):
        doc = self.getDocumentByFileName(filename)
        if doc:
            page = self._notebook.page_num(doc.widget)
            self._notebook.set_current_page(page)
            return doc.id
        else:
            return self._openDocument(filename)
    
    def openFileOpenDialog(self):
        window = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(title=_('Open File')
            , parent=window
            , action=Gtk.FileChooserAction.OPEN
            , buttons=(  Gtk.STOCK_CANCEL
                      , Gtk.ResponseType.CANCEL
                      , Gtk.STOCK_OPEN
                      , Gtk.ResponseType.ACCEPT
            
            )
        )
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            self.openDocument(filename)
        dialog.destroy()
    
    def openFileSaveAsDialog(self, doc):
        self.setActivePage(doc)
        window = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(title=_('Save File')
            , parent=window
            , action=Gtk.FileChooserAction.SAVE
            , buttons=( Gtk.STOCK_CANCEL
                      , Gtk.ResponseType.CANCEL
                      , Gtk.STOCK_SAVE
                      , Gtk.ResponseType.ACCEPT
            )
        )
        dialog.set_do_overwrite_confirmation(True);
        if doc.filename is None:
            dialog.set_current_name(doc.untitledName + Document.fileExtension)
        else:
            dialog.set_filename(doc.filename)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            doc.saveAs(filename)
        dialog.destroy()
    
    def _announceError(self, error, moreInfo=None):
            window = self.get_toplevel()
            dialog = Gtk.MessageDialog(
                window
                , Gtk.DialogFlags.DESTROY_WITH_PARENT
                , Gtk.MessageType.ERROR
                , Gtk.ButtonsType.CLOSE
                , error
            )
            if moreInfo is not None:
                dialog.format_secondary_text(moreInfo)
            
            # Destroy the dialog when the user responds to it
            # (e.g. clicks a button)
            def destroy(*args):
                dialog.destroy()
            dialog.connect('response', destroy)
            dialog.show()
    
    def _askOkCancel(self, question, moreInfo=None):
        window = self.get_toplevel()
        dialog = Gtk.MessageDialog(window, 0, Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.OK_CANCEL, question)
        if moreInfo is not None:
            dialog.format_secondary_text(moreInfo)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            return True
        return False
    
    def closeDocument(self, doc):
        ok = True
        if doc.hasChanges:
            self.setActivePage(doc)
            ok = self._askOkCancel(
                _('Close without Saving?'),
                _('All changes to the document will be lost.')
            )
        
        if not ok:
            return
        self._unregisterDocument(doc)
    
    def saveDocument(self, doc):
        if doc.filename is None:
            self.openFileSaveAsDialog(doc)
        else:
            doc.save()
    
    # global action handlers
    def menuFileNewHandler(self, widget):
        self.makeNewDocument()
    
    def menuFileOpenHandler(self, widget):
        self.openFileOpenDialog()
    
    def closeDocumentHandler(self, widget, id, *data):
        doc = self._documents.get(id, None)
        if doc is None:
            return
        self.closeDocument(doc)
    
    def quit(self):
        ok = True
        if self.hasChangedDocuments:
            ok = self._askOkCancel(
                _('Quit without Saving?'),
                _('There are documents with changes. All changes '
                  'will be lost.')
            )
        if ok:
            Gtk.main_quit()
            return False
        return True
    
    def quitHandler(self, *data):
        return self.quit()
    
    menuFileQuitHandler = quitHandler
    
    def menuFileCloseAllHandler(self, widget):
        active = self.activeDocument
        for doc in self._documents.values():
            self.closeDocument(doc)
        if active is not None:
            self.setActivePage(active)
        
    def menuFileSaveAllHandler(self, widget):
        active = self.activeDocument
        for doc in self._documents.values():
            if doc.hasChanges:
                self.saveDocument(doc)
        if active is not None:
            self.setActivePage(active)

    # document action handlers
    def menuFileCloseHandler(self, widget):
        if self.activeDocument is None:
            return
        self.closeDocument(self.activeDocument)
    
    def menuFileCloseOtherHandler(self, widget):
        if self.activeDocument is None:
            return
        active = self.activeDocument
        for doc in self._documents.values():
            if doc is not active:
                self.closeDocument(doc)
        self.setActivePage(active)
    
    def menuFileSaveDocumentHandler(self, widget):
        if self.activeDocument is None:
            return
        self.saveDocument(self.activeDocument)
    
    def menuFileSaveDocumentAsHandler(self, widget):
        if self.activeDocument is None:
            return
        self.openFileSaveAsDialog(self.activeDocument)
    
    def menuEditUndoHandler(self, widget):
        if self.activeDocument is None:
            return
        self.activeDocument.history.undo()
    
    def menuEditRedoHandler(self, widget):
        if self.activeDocument is None:
            return
        self.activeDocument.history.redo()
    
    
if __name__ == '__main__':
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    window = Gtk.Window()
    window.set_title(_('Multitoner Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)    
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = window.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER)
    multitoner = Multitoner()
    window.connect('delete-event', multitoner.quitHandler)
    window.add(multitoner)
    
    
    window.show_all()
    Gtk.main()
