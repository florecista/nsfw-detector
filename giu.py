import sys
from math import sqrt
from pathlib import Path

from PIL import Image
from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QToolBar, QLabel, \
    QDockWidget, QWidget, QFormLayout, QPushButton, QCheckBox, QScrollArea
from PySide6.QtGui import QIcon, QAction, QPixmap, QImage
from PySide6.QtCore import QSize, QDir
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

        # display the message in 5 seconds
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


        self.checkboxHentai = QCheckBox('Hentai', self)
        self.checkboxHentai.setChecked(True)
        layout.addRow(self.checkboxHentai)

        self.checkboxSexy = QCheckBox('Sexy', self)
        self.checkboxSexy.setChecked(True)
        layout.addRow(self.checkboxSexy)

        self.checkboxPorn = QCheckBox('Porn', self)
        self.checkboxPorn.setChecked(True)
        layout.addRow(self.checkboxPorn)

        self.checkboxDrawings = QCheckBox('Drawings', self)
        self.checkboxDrawings.setChecked(True)
        layout.addRow(self.checkboxDrawings)

        self.checkboxNeutral = QCheckBox('Neutral', self)
        self.checkboxNeutral.setChecked(True)
        layout.addRow(self.checkboxNeutral)

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

    def PIL_to_qimage(self, pil_img):
        temp = pil_img.convert('RGBA')
        return QImage(
            temp.tobytes('raw', "RGBA"),
            temp.size[0],
            temp.size[1],
            QImage.Format.Format_RGBA8888
        )

    def open_folder(self):

        selected_directory = QFileDialog.getExistingDirectory()

        if selected_directory:
            self.path = Path(selected_directory)
            self.set_title(selected_directory)

        fileList = QDir(selected_directory).entryList(["*.jpg"], filters=QDir.Files)
        fileCount = len(fileList)
        squaredNumber = round(sqrt(fileCount))
        if(squaredNumber < 8):
            squaredNumber = 8

        index = 0
        for i in range(squaredNumber):
            for j in range(squaredNumber):
                if index < fileCount:
                    size = (128, 128)
                    image_original = Image.open('images/' + fileList[index])
                    image_original.thumbnail(size, Image.Resampling.LANCZOS)
                    pixmap = QPixmap.fromImage(self.PIL_to_qimage(image_original))
                    btn = QLabel(fileList[index])
                    btn.setFixedWidth(128)
                    btn.setPixmap(pixmap)
                    index = index + 1
                else:
                    btn = QLabel('')
                self.gridLayout.addWidget(btn, i, j)

    def quit(self):
        if self.confirm_save():
            self.destroy()


if __name__ == '__main__':
    try:
        # show the app icon on the taskbar
        import ctypes

        myappid = 'matthewryan.analysistools.nsfwdetective.01'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    finally:
        app = QApplication(sys.argv)
        window = MainWindow()
        sys.exit(app.exec())

