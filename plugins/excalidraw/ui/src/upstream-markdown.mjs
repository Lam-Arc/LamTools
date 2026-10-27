var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));

// .build/obsidian-excalidraw-upstream/node_modules/lz-string/libs/lz-string.js
var require_lz_string = __commonJS({
  ".build/obsidian-excalidraw-upstream/node_modules/lz-string/libs/lz-string.js"(exports, module) {
    var LZString2 = (function() {
      var f = String.fromCharCode;
      var keyStrBase64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
      var keyStrUriSafe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$";
      var baseReverseDic = {};
      function getBaseValue(alphabet, character) {
        if (!baseReverseDic[alphabet]) {
          baseReverseDic[alphabet] = {};
          for (var i = 0; i < alphabet.length; i++) {
            baseReverseDic[alphabet][alphabet.charAt(i)] = i;
          }
        }
        return baseReverseDic[alphabet][character];
      }
      var LZString3 = {
        compressToBase64: function(input) {
          if (input == null) return "";
          var res = LZString3._compress(input, 6, function(a) {
            return keyStrBase64.charAt(a);
          });
          switch (res.length % 4) {
            // To produce valid Base64
            default:
            // When could this happen ?
            case 0:
              return res;
            case 1:
              return res + "===";
            case 2:
              return res + "==";
            case 3:
              return res + "=";
          }
        },
        decompressFromBase64: function(input) {
          if (input == null) return "";
          if (input == "") return null;
          return LZString3._decompress(input.length, 32, function(index) {
            return getBaseValue(keyStrBase64, input.charAt(index));
          });
        },
        compressToUTF16: function(input) {
          if (input == null) return "";
          return LZString3._compress(input, 15, function(a) {
            return f(a + 32);
          }) + " ";
        },
        decompressFromUTF16: function(compressed) {
          if (compressed == null) return "";
          if (compressed == "") return null;
          return LZString3._decompress(compressed.length, 16384, function(index) {
            return compressed.charCodeAt(index) - 32;
          });
        },
        //compress into uint8array (UCS-2 big endian format)
        compressToUint8Array: function(uncompressed) {
          var compressed = LZString3.compress(uncompressed);
          var buf = new Uint8Array(compressed.length * 2);
          for (var i = 0, TotalLen = compressed.length; i < TotalLen; i++) {
            var current_value = compressed.charCodeAt(i);
            buf[i * 2] = current_value >>> 8;
            buf[i * 2 + 1] = current_value % 256;
          }
          return buf;
        },
        //decompress from uint8array (UCS-2 big endian format)
        decompressFromUint8Array: function(compressed) {
          if (compressed === null || compressed === void 0) {
            return LZString3.decompress(compressed);
          } else {
            var buf = new Array(compressed.length / 2);
            for (var i = 0, TotalLen = buf.length; i < TotalLen; i++) {
              buf[i] = compressed[i * 2] * 256 + compressed[i * 2 + 1];
            }
            var result = [];
            buf.forEach(function(c) {
              result.push(f(c));
            });
            return LZString3.decompress(result.join(""));
          }
        },
        //compress into a string that is already URI encoded
        compressToEncodedURIComponent: function(input) {
          if (input == null) return "";
          return LZString3._compress(input, 6, function(a) {
            return keyStrUriSafe.charAt(a);
          });
        },
        //decompress from an output of compressToEncodedURIComponent
        decompressFromEncodedURIComponent: function(input) {
          if (input == null) return "";
          if (input == "") return null;
          input = input.replace(/ /g, "+");
          return LZString3._decompress(input.length, 32, function(index) {
            return getBaseValue(keyStrUriSafe, input.charAt(index));
          });
        },
        compress: function(uncompressed) {
          return LZString3._compress(uncompressed, 16, function(a) {
            return f(a);
          });
        },
        _compress: function(uncompressed, bitsPerChar, getCharFromInt) {
          if (uncompressed == null) return "";
          var i, value, context_dictionary = {}, context_dictionaryToCreate = {}, context_c = "", context_wc = "", context_w = "", context_enlargeIn = 2, context_dictSize = 3, context_numBits = 2, context_data = [], context_data_val = 0, context_data_position = 0, ii;
          for (ii = 0; ii < uncompressed.length; ii += 1) {
            context_c = uncompressed.charAt(ii);
            if (!Object.prototype.hasOwnProperty.call(context_dictionary, context_c)) {
              context_dictionary[context_c] = context_dictSize++;
              context_dictionaryToCreate[context_c] = true;
            }
            context_wc = context_w + context_c;
            if (Object.prototype.hasOwnProperty.call(context_dictionary, context_wc)) {
              context_w = context_wc;
            } else {
              if (Object.prototype.hasOwnProperty.call(context_dictionaryToCreate, context_w)) {
                if (context_w.charCodeAt(0) < 256) {
                  for (i = 0; i < context_numBits; i++) {
                    context_data_val = context_data_val << 1;
                    if (context_data_position == bitsPerChar - 1) {
                      context_data_position = 0;
                      context_data.push(getCharFromInt(context_data_val));
                      context_data_val = 0;
                    } else {
                      context_data_position++;
                    }
                  }
                  value = context_w.charCodeAt(0);
                  for (i = 0; i < 8; i++) {
                    context_data_val = context_data_val << 1 | value & 1;
                    if (context_data_position == bitsPerChar - 1) {
                      context_data_position = 0;
                      context_data.push(getCharFromInt(context_data_val));
                      context_data_val = 0;
                    } else {
                      context_data_position++;
                    }
                    value = value >> 1;
                  }
                } else {
                  value = 1;
                  for (i = 0; i < context_numBits; i++) {
                    context_data_val = context_data_val << 1 | value;
                    if (context_data_position == bitsPerChar - 1) {
                      context_data_position = 0;
                      context_data.push(getCharFromInt(context_data_val));
                      context_data_val = 0;
                    } else {
                      context_data_position++;
                    }
                    value = 0;
                  }
                  value = context_w.charCodeAt(0);
                  for (i = 0; i < 16; i++) {
                    context_data_val = context_data_val << 1 | value & 1;
                    if (context_data_position == bitsPerChar - 1) {
                      context_data_position = 0;
                      context_data.push(getCharFromInt(context_data_val));
                      context_data_val = 0;
                    } else {
                      context_data_position++;
                    }
                    value = value >> 1;
                  }
                }
                context_enlargeIn--;
                if (context_enlargeIn == 0) {
                  context_enlargeIn = Math.pow(2, context_numBits);
                  context_numBits++;
                }
                delete context_dictionaryToCreate[context_w];
              } else {
                value = context_dictionary[context_w];
                for (i = 0; i < context_numBits; i++) {
                  context_data_val = context_data_val << 1 | value & 1;
                  if (context_data_position == bitsPerChar - 1) {
                    context_data_position = 0;
                    context_data.push(getCharFromInt(context_data_val));
                    context_data_val = 0;
                  } else {
                    context_data_position++;
                  }
                  value = value >> 1;
                }
              }
              context_enlargeIn--;
              if (context_enlargeIn == 0) {
                context_enlargeIn = Math.pow(2, context_numBits);
                context_numBits++;
              }
              context_dictionary[context_wc] = context_dictSize++;
              context_w = String(context_c);
            }
          }
          if (context_w !== "") {
            if (Object.prototype.hasOwnProperty.call(context_dictionaryToCreate, context_w)) {
              if (context_w.charCodeAt(0) < 256) {
                for (i = 0; i < context_numBits; i++) {
                  context_data_val = context_data_val << 1;
                  if (context_data_position == bitsPerChar - 1) {
                    context_data_position = 0;
                    context_data.push(getCharFromInt(context_data_val));
                    context_data_val = 0;
                  } else {
                    context_data_position++;
                  }
                }
                value = context_w.charCodeAt(0);
                for (i = 0; i < 8; i++) {
                  context_data_val = context_data_val << 1 | value & 1;
                  if (context_data_position == bitsPerChar - 1) {
                    context_data_position = 0;
                    context_data.push(getCharFromInt(context_data_val));
                    context_data_val = 0;
                  } else {
                    context_data_position++;
                  }
                  value = value >> 1;
                }
              } else {
                value = 1;
                for (i = 0; i < context_numBits; i++) {
                  context_data_val = context_data_val << 1 | value;
                  if (context_data_position == bitsPerChar - 1) {
                    context_data_position = 0;
                    context_data.push(getCharFromInt(context_data_val));
                    context_data_val = 0;
                  } else {
                    context_data_position++;
                  }
                  value = 0;
                }
                value = context_w.charCodeAt(0);
                for (i = 0; i < 16; i++) {
                  context_data_val = context_data_val << 1 | value & 1;
                  if (context_data_position == bitsPerChar - 1) {
                    context_data_position = 0;
                    context_data.push(getCharFromInt(context_data_val));
                    context_data_val = 0;
                  } else {
                    context_data_position++;
                  }
                  value = value >> 1;
                }
              }
              context_enlargeIn--;
              if (context_enlargeIn == 0) {
                context_enlargeIn = Math.pow(2, context_numBits);
                context_numBits++;
              }
              delete context_dictionaryToCreate[context_w];
            } else {
              value = context_dictionary[context_w];
              for (i = 0; i < context_numBits; i++) {
                context_data_val = context_data_val << 1 | value & 1;
                if (context_data_position == bitsPerChar - 1) {
                  context_data_position = 0;
                  context_data.push(getCharFromInt(context_data_val));
                  context_data_val = 0;
                } else {
                  context_data_position++;
                }
                value = value >> 1;
              }
            }
            context_enlargeIn--;
            if (context_enlargeIn == 0) {
              context_enlargeIn = Math.pow(2, context_numBits);
              context_numBits++;
            }
          }
          value = 2;
          for (i = 0; i < context_numBits; i++) {
            context_data_val = context_data_val << 1 | value & 1;
            if (context_data_position == bitsPerChar - 1) {
              context_data_position = 0;
              context_data.push(getCharFromInt(context_data_val));
              context_data_val = 0;
            } else {
              context_data_position++;
            }
            value = value >> 1;
          }
          while (true) {
            context_data_val = context_data_val << 1;
            if (context_data_position == bitsPerChar - 1) {
              context_data.push(getCharFromInt(context_data_val));
              break;
            } else context_data_position++;
          }
          return context_data.join("");
        },
        decompress: function(compressed) {
          if (compressed == null) return "";
          if (compressed == "") return null;
          return LZString3._decompress(compressed.length, 32768, function(index) {
            return compressed.charCodeAt(index);
          });
        },
        _decompress: function(length, resetValue, getNextValue) {
          var dictionary = [], next, enlargeIn = 4, dictSize = 4, numBits = 3, entry = "", result = [], i, w, bits, resb, maxpower, power, c, data = { val: getNextValue(0), position: resetValue, index: 1 };
          for (i = 0; i < 3; i += 1) {
            dictionary[i] = i;
          }
          bits = 0;
          maxpower = Math.pow(2, 2);
          power = 1;
          while (power != maxpower) {
            resb = data.val & data.position;
            data.position >>= 1;
            if (data.position == 0) {
              data.position = resetValue;
              data.val = getNextValue(data.index++);
            }
            bits |= (resb > 0 ? 1 : 0) * power;
            power <<= 1;
          }
          switch (next = bits) {
            case 0:
              bits = 0;
              maxpower = Math.pow(2, 8);
              power = 1;
              while (power != maxpower) {
                resb = data.val & data.position;
                data.position >>= 1;
                if (data.position == 0) {
                  data.position = resetValue;
                  data.val = getNextValue(data.index++);
                }
                bits |= (resb > 0 ? 1 : 0) * power;
                power <<= 1;
              }
              c = f(bits);
              break;
            case 1:
              bits = 0;
              maxpower = Math.pow(2, 16);
              power = 1;
              while (power != maxpower) {
                resb = data.val & data.position;
                data.position >>= 1;
                if (data.position == 0) {
                  data.position = resetValue;
                  data.val = getNextValue(data.index++);
                }
                bits |= (resb > 0 ? 1 : 0) * power;
                power <<= 1;
              }
              c = f(bits);
              break;
            case 2:
              return "";
          }
          dictionary[3] = c;
          w = c;
          result.push(c);
          while (true) {
            if (data.index > length) {
              return "";
            }
            bits = 0;
            maxpower = Math.pow(2, numBits);
            power = 1;
            while (power != maxpower) {
              resb = data.val & data.position;
              data.position >>= 1;
              if (data.position == 0) {
                data.position = resetValue;
                data.val = getNextValue(data.index++);
              }
              bits |= (resb > 0 ? 1 : 0) * power;
              power <<= 1;
            }
            switch (c = bits) {
              case 0:
                bits = 0;
                maxpower = Math.pow(2, 8);
                power = 1;
                while (power != maxpower) {
                  resb = data.val & data.position;
                  data.position >>= 1;
                  if (data.position == 0) {
                    data.position = resetValue;
                    data.val = getNextValue(data.index++);
                  }
                  bits |= (resb > 0 ? 1 : 0) * power;
                  power <<= 1;
                }
                dictionary[dictSize++] = f(bits);
                c = dictSize - 1;
                enlargeIn--;
                break;
              case 1:
                bits = 0;
                maxpower = Math.pow(2, 16);
                power = 1;
                while (power != maxpower) {
                  resb = data.val & data.position;
                  data.position >>= 1;
                  if (data.position == 0) {
                    data.position = resetValue;
                    data.val = getNextValue(data.index++);
                  }
                  bits |= (resb > 0 ? 1 : 0) * power;
                  power <<= 1;
                }
                dictionary[dictSize++] = f(bits);
                c = dictSize - 1;
                enlargeIn--;
                break;
              case 2:
                return result.join("");
            }
            if (enlargeIn == 0) {
              enlargeIn = Math.pow(2, numBits);
              numBits++;
            }
            if (dictionary[c]) {
              entry = dictionary[c];
            } else {
              if (c === dictSize) {
                entry = w + w.charAt(0);
              } else {
                return null;
              }
            }
            result.push(entry);
            dictionary[dictSize++] = w + entry.charAt(0);
            enlargeIn--;
            w = entry;
            if (enlargeIn == 0) {
              enlargeIn = Math.pow(2, numBits);
              numBits++;
            }
          }
        }
      };
      return LZString3;
    })();
    if (typeof define === "function" && define.amd) {
      define(function() {
        return LZString2;
      });
    } else if (typeof module !== "undefined" && module != null) {
      module.exports = LZString2;
    } else if (typeof angular !== "undefined" && angular != null) {
      angular.module("LZString", []).factory("LZString", function() {
        return LZString2;
      });
    }
  }
});

// <stdin>
var import_lz_string = __toESM(require_lz_string());
var FRONTMATTER_KEYS = { plugin: { name: "excalidraw-plugin" } };
var FRONTMATTER = [
  "---",
  "",
  `${FRONTMATTER_KEYS.plugin.name}: parsed`,
  "tags: [excalidraw]",
  "",
  "---",
  "==\u26A0  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. \u26A0== You can decompress Drawing data with the command palette: 'Decompress current Excalidraw file'. For more info check in plugin settings under 'Saving'",
  "",
  ""
].join("\n");
function compress(data) {
  const compressed = import_lz_string.default.compressToBase64(data);
  let result = "";
  const chunkSize = 256;
  for (let i = 0; i < compressed.length; i += chunkSize) {
    result += `${compressed.slice(i, i + chunkSize)}

`;
  }
  return result.trim();
}
function decompress(data) {
  let cleanedData = "";
  const length = data.length;
  for (let i = 0; i < length; i++) {
    const char = data[i];
    if (char !== "\n" && char !== "\r") {
      cleanedData += char;
    }
  }
  return import_lz_string.default.decompressFromBase64(cleanedData);
}
var DRAWING_REG = /\n##? Drawing\n[^`]*(```json\n)([\s\S]*?)```\n/gm;
var DRAWING_REG_FALLBACK = /\n##? Drawing\n(```json\n)?(.*)(```)?(%%)?/gm;
var DRAWING_COMPRESSED_REG = /(\n##? Drawing\n[^`]*(?:```compressed-json\n))([\s\S]*?)(```\n)/gm;
var DRAWING_COMPRESSED_REG_FALLBACK = /(\n##? Drawing\n(?:```compressed-json\n)?)(.*)((```)?(%%)?)/gm;
var isCompressedMD = (data) => {
  return data.match(/```compressed-json\n/gm) !== null;
};
var getDecompressedScene = (data) => {
  let res = data.matchAll(DRAWING_COMPRESSED_REG);
  let parts;
  parts = res.next();
  if (parts.done) {
    res = data.matchAll(DRAWING_COMPRESSED_REG_FALLBACK);
    parts = res.next();
  }
  if (parts.value && parts.value.length > 1) {
    return [decompress(parts.value[2]), parts];
  }
  return [null, parts];
};
var changeThemeOfExcalidrawMD = (data) => {
  const compressed = isCompressedMD(data);
  let scene = compressed ? getDecompressedScene(data)[0] : data;
  if (!scene) {
    return data;
  }
  if (isObsidianThemeDark) {
    if ((scene.match(/"theme"\s*:\s*"light"\s*,/g) || []).length === 1) {
      scene = scene.replace(/"theme"\s*:\s*"light"\s*,/, `"theme": "dark",`);
    }
  } else if ((scene.match(/"theme"\s*:\s*"dark"\s*,/g) || []).length === 1) {
    scene = scene.replace(/"theme"\s*:\s*"dark"\s*,/, `"theme": "light",`);
  }
  if (compressed) {
    return data.replace(DRAWING_COMPRESSED_REG, `$1${compress(scene)}$3`);
  }
  return scene;
};
function getJSON(data) {
  let res;
  if (isCompressedMD(data)) {
    const [result, parts2] = getDecompressedScene(data);
    if (result) {
      return {
        scene: result.substring(0, result.lastIndexOf("}") + 1),
        pos: parts2.value.index
      };
    }
    return { scene: data, pos: parts2.value ? parts2.value.index : 0 };
  }
  res = data.matchAll(DRAWING_REG);
  let parts;
  parts = res.next();
  if (parts.done) {
    res = data.matchAll(DRAWING_REG_FALLBACK);
    parts = res.next();
  }
  if (parts.value && parts.value.length > 1) {
    const result = parts.value[2];
    return {
      scene: result.substring(0, result.lastIndexOf("}") + 1),
      pos: parts.value.index
    };
  }
  return { scene: data, pos: parts.value ? parts.value.index : 0 };
}
function getMarkdownDrawingSection(jsonString, compressed) {
  const result = compressed ? `## Drawing
\`\`\`compressed-json
${compress(
    jsonString
  )}
\`\`\`
%%` : `## Drawing
\`\`\`json
${jsonString}
\`\`\`
%%`;
  return result;
}
export {
  DRAWING_COMPRESSED_REG,
  FRONTMATTER,
  changeThemeOfExcalidrawMD,
  compress,
  decompress,
  getJSON,
  getMarkdownDrawingSection
};
