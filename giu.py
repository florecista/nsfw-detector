import sys
import re
from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit, QFileDialog, QMessageBox, QToolBar, QLabel, \
    QDockWidget, QWidget, QFormLayout, QLineEdit, QPushButton, QCheckBox, QVBoxLayout, QScrollArea, QSizePolicy
from PySide6.QtGui import QIcon, QAction, QPixmap
from PySide6.QtCore import QSize
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowIcon(QIcon('./assets/editor.png'))
        self.setGeometry(100, 100, 800, 600)

        self.title = 'Explorer'
        self.filters = 'Text Files (*.txt)'

        self.set_title()

        self.path = None

        self.main_view = QWidget(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        self.scrollAreaWidgetContents = QtWidgets.QWidget()
        self.gridLayout = QtWidgets.QGridLayout(self.scrollAreaWidgetContents)

        scroll.setWidget(self.scrollAreaWidgetContents)

        self.setCentralWidget(scroll)

        for i in range(10):
            for j in range(10):
                btn = QLabel('Test')
                pixmap = QPixmap('hacker-icon.png')
                btn.setPixmap(pixmap)
                self.gridLayout.addWidget(btn, i, j)

        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu('&File')
        help_menu = menu_bar.addMenu('&Help')

        # open menu item
        open_action = QAction(QIcon('./assets/open.png'), '&Open...', self)
        open_action.triggered.connect(self.open_folder)
        open_action.setStatusTip('Open a document')
        open_action.setShortcut('Ctrl+O')
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        # exit menu item
        exit_action = QAction(QIcon('./assets/exit.png'), '&Exit', self)
        exit_action.setStatusTip('Exit')
        exit_action.setShortcut('Alt+F4')
        exit_action.triggered.connect(self.quit)
        file_menu.addAction(exit_action)

        about_action = QAction(QIcon('./assets/about.png'), 'About', self)
        help_menu.addAction(about_action)
        about_action.setStatusTip('About')
        about_action.setShortcut('F1')

        # toolbar
        toolbar = QToolBar('Main ToolBar')
        self.addToolBar(toolbar)
        toolbar.setIconSize(QSize(16, 16))

        toolbar.addAction(open_action)
        toolbar.addSeparator()

        toolbar.addAction(exit_action)

        # status bar
        self.status_bar = self.statusBar()

        # display the a message in 5 seconds
        self.status_bar.showMessage('Ready', 5000)

        # add a permanent widget to the status bar
        self.character_count = QLabel("Length: 0")
        self.status_bar.addPermanentWidget(self.character_count)

        # dock widget
        self.dock = QDockWidget('Filter')
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock)

        search_form = QWidget()
        layout = QFormLayout(search_form)
        search_form.setLayout(layout)


        self.checkbox1 = QCheckBox('Hentai', self)
        self.checkbox1.setChecked(True)
        layout.addRow(self.checkbox1)

        self.checkbox2 = QCheckBox('Sexy', self)
        self.checkbox2.setChecked(True)
        layout.addRow(self.checkbox2)

        self.checkbox3 = QCheckBox('Porn', self)
        self.checkbox3.setChecked(True)
        layout.addRow(self.checkbox3)

        self.checkbox4 = QCheckBox('Drawings', self)
        self.checkbox4.setChecked(True)
        layout.addRow(self.checkbox4)

        self.checkbox5 = QCheckBox('Neutral', self)
        self.checkbox5.setChecked(True)
        layout.addRow(self.checkbox5)

        btn_search = QPushButton('Go', clicked=self.search)
        layout.addRow(btn_search)
        self.dock.setWidget(search_form)
        self.show()

    def show_search_dock(self):
        self.dock.show()

    def search(self):
        term = self.search_term.text()
        if not term:
            return

    def set_title(self, filename=None):
        title = f"{filename if filename else 'Untitled'} - {self.title}"
        self.setWindowTitle(title)

    def open_folder(self):
        filename, _ = QFileDialog.getOpenFileName(self, filter=self.filters)
        if filename:
            self.path = Path(filename)
            self.set_title(filename)

    def quit(self):
        if self.confirm_save():
            self.destroy()


if __name__ == '__main__':
    try:
        # show the app icon on the taskbar
        import ctypes

        myappid = 'yourcompany.yourproduct.subproduct.version'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    finally:
        app = QApplication(sys.argv)
        window = MainWindow()
        sys.exit(app.exec())

