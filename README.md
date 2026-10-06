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

Open **Help > About** for application copyright information, model provenance
and checksums, and a versioned list of direct third-party dependencies and their
licenses. The application is currently all rights reserved; a separate
application license has not yet been distributed. Third-party libraries and
model assets remain governed by their respective licenses.

## Scanning and filtering

The desktop application scans `.jpg`, `.jpeg`, `.png`, and `.webp` images. Choose
**Select and scan directory** to select a directory and begin processing it
immediately. Enable **Include subdirectories** first when you want a recursive
scan, or change the option and choose **Rescan selected directory**. Scans run in
the background and can be cancelled from the progress area or progress dialog.

The main window keeps the current scan stage, progress, and final result summary
visible. For longer scans, a cancellable window-modal progress dialog also
appears. Filter checkbox changes update the already-classified results
immediately; filtering never starts a new scan or runs the model again.

Each image is classified once per scan. Changing the display filters uses the
cached results and does not run the model again. Classification scores are also
stored in a local SQLite cache keyed by full path, file size, modification time,
model ID, and model version. Unchanged files can therefore be reused in later
scans and after restarting the application.

Directory discovery and classification both run in the background. Recursive
discovery reports inaccessible locations without abandoning the rest of the
tree, model inference is batched, and thumbnails are loaded incrementally so a
large result set does not have to be rendered in one blocking operation.

The **NSFW** common filter uses the active model's configurable threshold. With
the bundled GantMan model, the NSFW score is the combined
`hentai + porn + sexy` probability. Select a displayed image to see its full
path, category confidence scores, and any model-supplied region detections in
the Scan details panel.

## Configuration and models

Open **Settings > Configuration** (or press `Ctrl+,`) to choose the default model,
adjust its NSFW threshold, and set whether scans include subdirectories by
default. Settings are stored with Qt's platform settings service and restored on
the next launch.

The bundled **GantMan MobileNet** remains the default for compatibility. The
following local models are available:

- **GantMan MobileNet** — legacy Drawings, Hentai, Neutral, Porn, and Sexy
  categories.
- **NudeNet 320n** — the recommended fast option when the task is specifically
  detecting exposed anatomical regions. Review the NudeNet package and
  repository licensing before distributing it as part of another application.
- **OpenNSFW2** — an MIT-licensed broad pornographic-content classifier.

The filter panel has stable All classified images, NSFW, and SFW controls,
followed by model-specific category filters. These category controls are
generated from the selected model's capabilities.

## Model files and cache

Model assets are copied or downloaded into an application-owned, versioned model
directory and checked with SHA-256 before loading. Incomplete or corrupt files
are not reused. On Windows the default location is:

```text
%LOCALAPPDATA%\florecista\NSFW Detector\models
```

Set `NSFW_DETECTOR_DATA_DIR` to relocate both application-managed models and the
classification cache, or `NSFW_DETECTOR_MODEL_DIR` to relocate only model
assets. The classification cache is normally stored beside the models under
`cache/classification.sqlite3`.

## Private model evaluation

The `evaluation/private` directory contains ignored folders for safe, swimwear,
artistic nudity, explicit nudity, drawings, and difficult false-positive test
images. Keep sensitive evaluation material local; Git tracks only the empty
folder structure and its instructions.

### Troubleshooting
If a validated model cannot be loaded, the application reports the model and
error. Model files now live in the application-owned location above rather than
the system temporary directory.

# Credits

Thanks to https://github.com/GantMan/nsfw_model/ for their model.

Additional model options use:

- https://github.com/notAI-tech/NudeNet
- https://github.com/bhky/opennsfw2
