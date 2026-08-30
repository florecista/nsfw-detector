# NSFW Detector
Goal is to build a desktop application that can :
* Open a folder
* Display images of the folder as thumbnails
* Using a filter panel in the UI hide and show by Genre
* Display a properies panel to give high level statistics of the folder, i.e. quantity of images by Genre

## Download and install

```sh
$ git clone https://github.com/florecista/nsfw-detector

$ cd nsfw-detector

$ pip install -U -r requirements.txt

```
## Run

```sh
$ python gui.py

```

## Scanning and filtering

The desktop application scans `.jpg`, `.jpeg`, `.png`, and `.webp` images. Enable
**Include subdirectories** before opening a directory when you want a recursive
scan. Scans run in the background and can be cancelled from the progress dialog.

Each image is classified once per scan. Changing the display filters uses the
cached results and does not run the model again. The **NSFW** common filter uses
the active model's configurable NSFW threshold. With the bundled GantMan model,
the NSFW score is the combined `hentai + porn + sexy` probability. Select a
displayed image to see its full path and category confidence scores in the Scan
details panel.

## Configuration and models

Open **Settings > Configuration** (or press `Ctrl+,`) to choose the default model,
adjust its NSFW threshold, and set whether scans include subdirectories by
default. Settings are stored with Qt's platform settings service and restored on
the next launch.

The bundled **GantMan MobileNet (five categories)** model remains the default.
The filter panel has stable All classified images, NSFW, and SFW controls followed
by model-specific category filters. Those category controls are generated from
the selected model's capabilities, so a future binary model can expose only its
supported controls without inventing Drawings, Hentai, Neutral, Porn, or Sexy
scores.

### Troubleshooting
There can be issues with the model. When there is you can remove the existing one from the temp directory. On next start up a new model will be generated.
You can find the existing model at - <user_home_dir>\AppData\Local\Temp\tfhub_modules

# Credits

Thanks to https://github.com/GantMan/nsfw_model/ for their model.
