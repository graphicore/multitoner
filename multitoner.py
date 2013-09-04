#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
import sys
import os
import json
from gi.repository import Gtk, Gdk, GObject
from gtkinktool import InksEditor, ModelCurves, ModelInk, History, GradientWorker

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
    __gsignals__ = {
        'close': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                  # id
                  GObject.TYPE_INT, ))
    }
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

class Document(object):
    untitledName = _('untitled')
    
    def __init__(self, gradientWorker, name=None, filename=None, data=None):
        if name is None:
            name=self.untitledName
        if data is None:
            data = {}
        self._gradientWorker = gradientWorker
        model = ModelCurves(ChildModel=ModelInk, **data)
        history = History(model)
        inksEditor = InksEditor(model, self._gradientWorker)
        widget_id = id(inksEditor)
        label = Label(widget_id, name)
        
        self.id = id(self)
        self.history = history
        self.model = model
        self.widget = inksEditor
        self.label = label
        self.filename = filename

class Multitoner(Gtk.Grid):
    fileExtension = '.mtt' # .m(ulti)t(oner)t(ool)
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
    
    def switchPageHandler(self, widget, page, page_num):
        self.setCurrentPage(page_num)
    
    def pageAddRemoveHandler(self,*data):
        self.setCurrentPage()
    
    def getDocumentByPage(self, page):
        widget = self._notebook.get_nth_page(page)
        return self.getDocumentByWidget(widget)
    
    def getDocumentByWidget(self, widget):
        for doc in self._documents.values():
            if doc.widget == widget:
                return doc
        return None
    
    def getDocumentByFileName(self, filename):
        for doc in self._documents.values():
            if doc.filename == filename:
                return doc
        return None
    
    def setCurrentPage(self, page=None):
        if page is None:
            page = self._notebook.get_current_page()
        doc = self.getDocumentByPage(page)
        if doc is None:
            # there is no current page
            self._documentActions.set_sensitive(False)
        else:
            self._documentActions.set_sensitive(True)
        # activeDocument is either a Document or None 
        self.activeDocument = doc
    
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
            , ('FileNew', Gtk.STOCK_NEW, _('New …'), '<Ctrl>n',
               _('Start a new document.'), self.menuFileNewHandler)
            , ('FileQuit', Gtk.STOCK_QUIT, _('Quit'), '<ctrl>q',
               None, self.menuFileQuitHandler)
            , ('FileOpen', Gtk.STOCK_OPEN, _('Open'), '<Ctrl>o',
               _('Open a document.'), self.menuFileOpenHandler)
            ])
        
        # recent files chooser
        # does only .mtt files
        recentAction = Gtk.RecentAction.new_for_manager('FileOpenRecent',
            _('Recent Files'), None, None, None)
        recentFilter= Gtk.RecentFilter()
        recentFilter.add_pattern ("*" + self.fileExtension);
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
            ])
        actionGroup.set_sensitive(False)
        return actionGroup
    
    def makeDocument(self, name=None, filename=None, data=None):
        doc = Document(self._gradientWorker, name, filename, data)
        doc.label.connect('close', self.closeDocumentHandler, doc.id)
        page = self._notebook.append_page(doc.widget, doc.label)
        self._notebook.set_tab_reorderable(doc.widget, True)
        doc.widget.show_all()
        self._notebook.set_current_page(page)
        self._documents[doc.id] = doc
        return doc.id
    
    def openDocument(self, filename):
        doc = self.getDocumentByFileName(filename)
        if doc:
            page = self._notebook.page_num(doc['widget'])
            self._notebook.set_current_page(page)
            return doc.id
        else:
            name = os.path.basename(filename)
            with open(filename, 'r') as f:
                data = json.load(f)
            return self.makeDocument(name, filename, data)
    
    def saveDocument(self, doc, filename):
        data = doc.model.getArgs()
        
        
        data = json.dumps(data, sort_keys=True, indent=2, separators=(',', ': '))
        with open(filename, 'w') as f:
            f.write(data)
        
        doc.filename = filename
        doc.label.setLabelText(os.path.basename(filename))
    
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
            dialog.set_current_name(doc.untitledName + self.fileExtension)
        else:
            dialog.set_filename(doc.filename)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            self.saveDocument(doc, filename)
        dialog.destroy()
    
    # global action handlers
    def menuFileNewHandler(self, widget):
        self.makeDocument()
    
    def menuFileOpenHandler(self, widget):
        self.openFileOpenDialog()
    
    def closeDocumentHandler(self, widget, id, *data):
        page = self._notebook.page_num(self._documents[id].widget)
        self._notebook.remove_page(page)
        print 'closeDocumentHandler Todo: ask when there are unsafed changes'
        del self._documents[id]
        
    def menuFileQuitHandler(self, widget):
        Gtk.main_quit()
    
    # document action handlers
    def menuFileSaveDocumentHandler(self, widget):
        if self.activeDocument is None:
            return
        if self.activeDocument.filename is None:
            self.openFileSaveAsDialog(self.activeDocument)
        else:
            self.saveDocument(self.activeDocument, self.activeDocument.filename)
    
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
    window.connect('destroy', Gtk.main_quit)
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = window.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    multitoner = Multitoner()
    window.add(multitoner)
    
    window.show_all()
    Gtk.main()
