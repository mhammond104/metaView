# metaView GenAI Image and Experiment Manager

**metaView** is a cross-platform desktop application for browsing AI-generated images, inspecting embedded generation metadata, comparing generations, and managing experimentation with generation parameters and techniques.

The application runs on Linux, MacOS, and Windows. Executable binaries can be downloaded from the 'Releases' page.

> Current status: as of v0.2.1, the application functions well as an image browser with comprehensive metadata comparison functionality, and embryonic experimentation management tools. Additional development of the experimentation toolset is planned for the v0.3.0 release.


<img src="screenshots/main_window.png" width="900">

## Features

- Filesystem explorer with thumbnail browser, image preview, and metadata summary panel
- Search and filtering by filename, prompt, model, sampler, scheduler, and star rating
- Side-by-side image compare function with A/B comparison of parameters such as model, sampler, scheduler, seed, and resolution
- Parameter and LoRA difference highlighting in the Compare view
- Similarity Search to display all images with identical model, LoRAs, seed, prompt, sampler, scheduler, and/or resolution
- Prompt Library system to keep track of favourite and frequently-used prompts
- Prompts can be tagged and star-rated, and all images with a given prompt can be quickly displayed
- 5 star rating system for images with rating filter and rating-aware sorting in the thumbnail browser
- Experiment View identifies all images in the current directory sharing a given prompt for a quick overview of variations
- Eye-friendly dark-style interface
- Live updates in the thumbnail browser as directory contents change
- Ablitity to drag-and-drop the image workflow from the application onto ComfyUI or a file explorer

## Roadmap

### Planned for v0.3.0

- Experiment Management
- Saved experiments with notes and conclusions
- Experiment tagging
- Automatic experiment statistics
- Improved search and filtering

### Longer-term ideas

- Prompt evolution history
- LoRA analytics
- Advanced metadata search
- Contact sheet export

## Privacy and stored data

Ratings and Prompt Library entries are stored locally in the operating system's application-data area. metaView does not need to modify source images to save ratings or prompt-library records.

## Contributing

Bug reports and focused pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

metaView is released under the [MIT License](LICENSE).
