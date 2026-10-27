// <stdin>
var MARKDOWN_IMAGE_EMBEDDED_FILE_TOKEN = "markdown-image";
var OriginalWriter = class {
  generateMDBase(deletedElements = []) {
    const syncTextLinks = this.plugin.settings.syncElementLinkWithText;
    let outString = this.textElementCommentedOut ? "%%\n" : "";
    outString += `# Excalidraw Data

## Text Elements
`;
    if (this.plugin.settings.addDummyTextElement) {
      outString += `
^_dummy!_

`;
    }
    const textElementLinks = /* @__PURE__ */ new Map();
    const uniqueSceneElementsById = /* @__PURE__ */ new Map();
    for (const element of this.scene.elements) {
      uniqueSceneElementsById.set(
        element.id,
        uniqueSceneElementsById.has(element.id) ? null : element
      );
    }
    for (const key of this.textElements.keys()) {
      const element = uniqueSceneElementsById.get(key);
      const elementString = this.textElements.get(key).raw;
      if (element && element.link && (!syncTextLinks || element.rawText === element.originalText)) {
        textElementLinks.set(key, element.link);
      }
      outString += `${elementString} ^${key}

`;
    }
    if (this.elementLinks.size > 0 || textElementLinks.size > 0) {
      outString += `## Element Links
`;
      for (const key of this.elementLinks.keys()) {
        outString += `${key}: ${this.elementLinks.get(key)}

`;
      }
      for (const key of textElementLinks.keys()) {
        outString += `${key}: ${textElementLinks.get(key)}

`;
      }
    }
    outString += this.equations.size > 0 || this.files.size > 0 || this.markdownImages.size > 0 ? "## Embedded Files\n" : "";
    if (this.equations.size > 0) {
      for (const key of this.equations.keys()) {
        outString += `${key}: $$${this.equations.get(key).latex.trim()}$$

`;
      }
    }
    if (this.files.size > 0) {
      for (const key of this.files.keys()) {
        const PATHREG = /(^[^#|]*)/;
        const ef = this.files.get(key);
        if (ef.isHyperLink || ef.isLocalLink) {
          outString += `${key}: ${ef.hyperlink}

`;
        } else {
          const path = ef.file ? ef.linkParts.original.replace(
            PATHREG,
            this.app.metadataCache.fileToLinktext(ef.file, this.file.path)
          ) : ef.linkParts.original;
          const colorMap = ef.colorMap ? ` ${JSON.stringify(ef.colorMap)}` : "";
          outString += `${key}: [[${path}]]${colorMap}

`;
        }
      }
    }
    if (this.markdownImages.size > 0) {
      for (const key of this.markdownImages.keys()) {
        outString += `${key}: ${MARKDOWN_IMAGE_EMBEDDED_FILE_TOKEN}

`;
      }
    }
    const sceneJSONstring = JSON.stringify(
      {
        type: this.scene.type,
        version: this.scene.version,
        source: this.scene.source,
        elements: this.scene.elements.concat(deletedElements),
        appState: this.scene.appState,
        files: this.scene.files
      },
      null,
      "	"
    );
    return { outString, sceneJSONstring };
  }
};
var generateMDBase = OriginalWriter.prototype.generateMDBase;
function updateElementIdsInScene({ elements: sceneElements }, elementToChange, newID) {
  if (elementToChange.type === "text") {
    const textElement = elementToChange;
    if (textElement.containerId) {
      const containerEl = sceneElements.find(
        (el) => el.id === textElement.containerId
      );
      containerEl.boundElements?.filter((x) => x.id === textElement.id).forEach((x) => {
        x.id = newID;
      });
    }
  }
  if (elementToChange.boundElements?.length > 0) {
    elementToChange.boundElements.forEach((binding) => {
      const boundEl = sceneElements.find(
        (el) => el.id === binding.id
      );
      if (!boundEl) {
        return;
      }
      boundEl.boundElements?.filter((x) => x.id === elementToChange.id).forEach((x) => {
        x.id = newID;
      });
      if (boundEl.type === "text") {
        boundEl.containerId = newID;
      }
      if (boundEl.type === "arrow") {
        const arrow = boundEl;
        if (arrow.startBinding?.elementId === elementToChange.id) {
          arrow.startBinding.elementId = newID;
        }
        if (arrow.endBinding?.elementId === elementToChange.id) {
          arrow.endBinding.elementId = newID;
        }
      }
    });
  }
  if (elementToChange.type === "frame") {
    sceneElements.filter((el) => el.frameId === elementToChange.id).forEach((x) => {
      x.frameId = newID;
    });
  }
  elementToChange.id = newID;
}
export {
  generateMDBase,
  updateElementIdsInScene
};
