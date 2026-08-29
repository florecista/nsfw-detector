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
cached results and does not run the model again. **All NSFW** matches images whose
combined `hentai + porn + sexy` score is at least 70 percent. Select a displayed
image to see its full path and category confidence scores in the Scan details
panel.

### Troubleshooting
There can be issues with the model. When there is you can remove the existing one from the temp directory. On next start up a new model will be generated.
You can find the existing model at - <user_home_dir>\AppData\Local\Temp\tfhub_modules

# Credits

Thanks to https://github.com/GantMan/nsfw_model/ for their model.
