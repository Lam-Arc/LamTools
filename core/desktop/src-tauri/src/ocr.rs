//! 截图取字：走 Windows 自带的 OCR 引擎（`Windows.Media.Ocr`）。
//!
//! user:“优先用 Windows 内置 OCR（Windows.Media.Ocr）…语言包缺失时返回明确错误码（不要静默空字符串）；
//! 不联网、不分发第三方二进制”+
//! (识别只用系统自带的引擎和系统自带的解码器：不加模型文件、不发网络请求、不下载任何东西。
//!  系统没装对应语言的 OCR 包时必须报 `ocr_language_missing` 并把可安装/已安装的语言列出来，
//!  绝不能用空字符串冒充「这张图里没有字」。)
//!
//! 入参是一张图片的 base64（可以直接是 `data:image/png;base64,...` 这种 data URL），
//! 解码交给 `BitmapDecoder`，所以这里不需要额外的图片解码 crate。
//! 裁剪不在这里做：Python 工具用 PIL 裁、Ping 界面用 canvas 裁，进来的图就是最终要认的那块。

use serde::Serialize;

/// 一行识别结果。
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct OcrLine {
    /// 这一行的文字（系统按词拼好的行文本）。
    pub text: String,
    /// 这一行在图片里的位置 `[x, y, width, height]`，单位是图片像素。
    pub bounds: [i32; 4],
}

/// 一次识别的完整结果。
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct OcrOutput {
    /// 整张图的文字，行之间用 `\n` 分隔。识别不到文字时是空字符串（这是「图里没字」，不是错误）。
    pub text: String,
    pub lines: Vec<OcrLine>,
    /// 实际使用的识别语言（BCP-47，例如 `zh-Hans-CN`）。
    pub language: String,
    pub image_width: u32,
    pub image_height: u32,
    /// 引擎允许的最大边长；超过它系统会直接失败，所以提前判断并说明。
    pub max_image_dimension: u32,
    /// 系统里可用的识别语言，用户据此知道缺哪个包。
    pub available_languages: Vec<String>,
}

/// user:“统一错误模型：{code, message, retriable}”+(前端要能据此给出「去装语言包」这类可操作提示)。
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct OcrError {
    pub code: String,
    pub message: String,
    pub retriable: bool,
}

impl OcrError {
    fn new(code: &str, message: impl Into<String>, retriable: bool) -> Self {
        Self { code: code.to_string(), message: message.into(), retriable }
    }

    /// user:“语言包缺失时返回明确错误码”+(缺包和「图里没字」必须能区分开)。
    pub fn language_missing(requested: &str, available: &[String]) -> Self {
        let installed = if available.is_empty() {
            "系统里一个 OCR 语言包都没有".to_string()
        } else {
            format!("系统里已安装的识别语言：{}", available.join("、"))
        };
        Self::new(
            "ocr_language_missing",
            format!(
                "系统没有可用的 OCR 语言包（请求的语言：{requested}；{installed}）。\
                 在 Windows「设置 → 时间和语言 → 语言和区域」里给目标语言添加「可选功能 → 光学字符识别」后再试。"
            ),
            false,
        )
    }

    pub fn invalid_image(message: impl Into<String>) -> Self {
        Self::new("ocr_invalid_image", message, false)
    }

    pub fn too_large(width: u32, height: u32, max: u32) -> Self {
        Self::new(
            "ocr_image_too_large",
            format!("图片 {width}x{height} 超过 OCR 引擎上限 {max}，先缩小或只框选要识别的区域"),
            false,
        )
    }

    pub fn engine(message: impl Into<String>) -> Self {
        Self::new("ocr_engine_failed", message, true)
    }

    pub fn unsupported_platform() -> Self {
        Self::new(
            "ocr_unsupported_platform",
            "截图取字只支持 Windows（用的是系统自带的 Windows.Media.Ocr）",
            false,
        )
    }
}

/// 把工具/界面传进来的图片字段解成字节。
///
/// 两种写法都认：裸 base64，或者 `data:image/png;base64,...` 这种 data URL
/// （Ping 界面用 `canvas.toDataURL()` 拿到的就是后者）。空白与换行会被忽略。
pub fn decode_image_input(input: &str) -> Result<Vec<u8>, OcrError> {
    use base64::Engine as _;

    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Err(OcrError::invalid_image("没有收到图片数据"));
    }
    let payload = match trimmed.strip_prefix("data:") {
        Some(rest) => match rest.split_once(";base64,") {
            Some((_, data)) => data,
            None => {
                return Err(OcrError::invalid_image(
                    "data URL 只支持 base64 编码（形如 data:image/png;base64,...）",
                ))
            }
        },
        None => trimmed,
    };
    let cleaned: String = payload.chars().filter(|c| !c.is_whitespace()).collect();
    if cleaned.is_empty() {
        return Err(OcrError::invalid_image("图片数据是空的"));
    }
    let standard = base64::engine::general_purpose::STANDARD;
    if let Ok(bytes) = standard.decode(cleaned.as_bytes()) {
        return Ok(bytes);
    }
    // 有些调用方会省掉尾部 `=`，按无填充再试一次。
    base64::engine::general_purpose::STANDARD_NO_PAD
        .decode(cleaned.trim_end_matches('=').as_bytes())
        .map_err(|error| OcrError::invalid_image(format!("图片不是合法的 base64：{error}")))
}

/// 识别一张图片里的文字。`language` 为空时用用户配置语言，其次退到系统里任一已安装语言。
#[cfg(windows)]
pub fn recognize(bytes: &[u8], language: Option<&str>) -> Result<OcrOutput, OcrError> {
    platform::recognize(bytes, language)
}

#[cfg(not(windows))]
pub fn recognize(_bytes: &[u8], _language: Option<&str>) -> Result<OcrOutput, OcrError> {
    Err(OcrError::unsupported_platform())
}

#[cfg(windows)]
mod platform {
    use super::{OcrError, OcrLine, OcrOutput};
    use windows::core::HSTRING;
    use windows::Foundation::Rect;
    use windows::Globalization::Language;
    use windows::Graphics::Imaging::{BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat, SoftwareBitmap};
    use windows::Media::Ocr::OcrEngine;
    use windows::Storage::Streams::{DataWriter, InMemoryRandomAccessStream};

    /// WinRT 的激活要求线程处在某个 apartment 里。桌面进程里 MTA 一直存在，
    /// 命令跑在工作线程上也能直接激活；点一次就不释放，避免每个线程各初始化一遍。
    fn ensure_apartment() {
        static ONCE: std::sync::Once = std::sync::Once::new();
        ONCE.call_once(|| unsafe {
            let _ = windows::Win32::System::Com::CoIncrementMTAUsage();
        });
    }

    /// 系统里已安装的识别语言标签。测试也用它区分「没装包」与「装了包但识别为空」。
    pub(super) fn available_languages() -> Vec<String> {
        let Ok(list) = OcrEngine::AvailableRecognizerLanguages() else {
            return Vec::new();
        };
        let mut tags = Vec::new();
        for language in &list {
            if let Ok(tag) = language.LanguageTag() {
                tags.push(tag.to_string());
            }
        }
        tags
    }

    /// 用系统解码器把图片字节变成 OCR 认的 Bgra8 位图。
    fn decode(bytes: &[u8]) -> Result<SoftwareBitmap, OcrError> {
        let stream = InMemoryRandomAccessStream::new()
            .map_err(|error| OcrError::engine(format!("创建内存流失败：{error}")))?;
        let writer = DataWriter::CreateDataWriter(&stream)
            .map_err(|error| OcrError::engine(format!("创建写入器失败：{error}")))?;
        writer
            .WriteBytes(bytes)
            .map_err(|error| OcrError::invalid_image(format!("写入图片字节失败：{error}")))?;
        writer
            .StoreAsync()
            .and_then(|operation| operation.get())
            .map_err(|error| OcrError::invalid_image(format!("写入图片字节失败：{error}")))?;
        let _ = writer.DetachStream();
        stream
            .Seek(0)
            .map_err(|error| OcrError::engine(format!("回绕内存流失败：{error}")))?;
        let decoder = BitmapDecoder::CreateAsync(&stream)
            .map_err(|error| OcrError::invalid_image(format!("图片格式不被支持：{error}")))?
            .get()
            .map_err(|error| OcrError::invalid_image(format!("图片解码失败：{error}")))?;
        let bitmap = decoder
            .GetSoftwareBitmapAsync()
            .map_err(|error| OcrError::invalid_image(format!("图片转位图失败：{error}")))?
            .get()
            .map_err(|error| OcrError::invalid_image(format!("图片转位图失败：{error}")))?;
        // OCR 引擎只接受 Bgra8，alpha 用 Ignore（截图里本来也没有透明区域）。
        SoftwareBitmap::ConvertWithAlpha(&bitmap, BitmapPixelFormat::Bgra8, BitmapAlphaMode::Ignore)
            .map_err(|error| OcrError::invalid_image(format!("图片转 Bgra8 失败：{error}")))
    }

    fn build_engine(language: Option<&str>, available: &[String]) -> Result<OcrEngine, OcrError> {
        if let Some(tag) = language.map(str::trim).filter(|tag| !tag.is_empty()) {
            let requested = Language::CreateLanguage(&HSTRING::from(tag))
                .map_err(|_| OcrError::language_missing(tag, available))?;
            return OcrEngine::TryCreateFromLanguage(&requested)
                .map_err(|_| OcrError::language_missing(tag, available));
        }
        if let Ok(engine) = OcrEngine::TryCreateFromUserProfileLanguages() {
            return Ok(engine);
        }
        // 用户配置语言里没有 OCR 能力时，退到系统里任意一个已安装的识别语言。
        if let Ok(list) = OcrEngine::AvailableRecognizerLanguages() {
            if list.Size().unwrap_or(0) > 0 {
                if let Ok(first) = list.GetAt(0) {
                    if let Ok(engine) = OcrEngine::TryCreateFromLanguage(&first) {
                        return Ok(engine);
                    }
                }
            }
        }
        Err(OcrError::language_missing("用户配置语言", available))
    }

    fn union(left: Rect, right: Rect) -> Rect {
        let x = left.X.min(right.X);
        let y = left.Y.min(right.Y);
        let right_edge = (left.X + left.Width).max(right.X + right.Width);
        let bottom_edge = (left.Y + left.Height).max(right.Y + right.Height);
        Rect { X: x, Y: y, Width: right_edge - x, Height: bottom_edge - y }
    }

    pub fn recognize(bytes: &[u8], language: Option<&str>) -> Result<OcrOutput, OcrError> {
        ensure_apartment();
        let available = available_languages();
        let max_image_dimension = OcrEngine::MaxImageDimension().unwrap_or(0);
        let bitmap = decode(bytes)?;
        let image_width = bitmap.PixelWidth().unwrap_or(0).max(0) as u32;
        let image_height = bitmap.PixelHeight().unwrap_or(0).max(0) as u32;
        if max_image_dimension > 0
            && (image_width > max_image_dimension || image_height > max_image_dimension)
        {
            return Err(OcrError::too_large(image_width, image_height, max_image_dimension));
        }
        let engine = build_engine(language, &available)?;
        let engine_language = engine
            .RecognizerLanguage()
            .and_then(|value| value.LanguageTag())
            .map(|tag| tag.to_string())
            .unwrap_or_default();
        let result = engine
            .RecognizeAsync(&bitmap)
            .map_err(|error| OcrError::engine(format!("识别没有启动：{error}")))?
            .get()
            .map_err(|error| OcrError::engine(format!("识别失败：{error}")))?;
        let text = result.Text().map(|value| value.to_string()).unwrap_or_default();
        let mut lines = Vec::new();
        if let Ok(view) = result.Lines() {
            for line in &view {
                let line_text = line.Text().map(|value| value.to_string()).unwrap_or_default();
                // 行位置取这一行所有词的外接框；系统没给词时退回全零。
                let mut box_: Option<Rect> = None;
                if let Ok(words) = line.Words() {
                    for word in &words {
                        if let Ok(word_box) = word.BoundingRect() {
                            box_ = Some(match box_ {
                                Some(current) => union(current, word_box),
                                None => word_box,
                            });
                        }
                    }
                }
                let bounds = box_
                    .map(|value| {
                        [
                            value.X.round() as i32,
                            value.Y.round() as i32,
                            value.Width.round() as i32,
                            value.Height.round() as i32,
                        ]
                    })
                    .unwrap_or([0, 0, 0, 0]);
                lines.push(OcrLine { text: line_text, bounds });
            }
        }
        Ok(OcrOutput {
            text,
            lines,
            language: engine_language,
            image_width,
            image_height,
            max_image_dimension,
            available_languages: available,
        })
    }
}

/// 桌面命令：`ocr_image({ image, language? })`。
///
/// user:“可在 Rust 侧加一个命令（例如 ocr_image(bytes) → {text, lines[]}）”+
/// (界面和 Agent 工具都走这一个命令：进来的图已经裁好，出参给整段文字加逐行位置)。
#[tauri::command]
pub async fn ocr_image(image: String, language: Option<String>) -> Result<OcrOutput, OcrError> {
    // 识别是几十到几百毫秒的阻塞活，放到阻塞线程池，别占 IPC 的异步运行时。
    tauri::async_runtime::spawn_blocking(move || {
        let bytes = decode_image_input(&image)?;
        recognize(&bytes, language.as_deref())
    })
    .await
    .map_err(|error| OcrError::engine(format!("识别任务异常终止：{error}")))?
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_PNG: &[u8] = include_bytes!("../tests/fixtures/ocr-known-text.png");
    /// 样图里画的文字；断言只比这几段，避免不同语言包的大小写/空格差异。
    const SAMPLE_WORDS: [&str; 2] = ["Sunday", "2024"];

    fn base64_of(bytes: &[u8]) -> String {
        use base64::Engine as _;
        base64::engine::general_purpose::STANDARD.encode(bytes)
    }

    // user:“先写测试：工具输出形状”+(图片字段两种写法都要认，坏数据要有明确错误码)。
    #[test]
    fn decodes_raw_base64_and_data_url() {
        let encoded = base64_of(SAMPLE_PNG);
        assert_eq!(decode_image_input(&encoded).unwrap(), SAMPLE_PNG);
        let data_url = format!("data:image/png;base64,{encoded}");
        assert_eq!(decode_image_input(&data_url).unwrap(), SAMPLE_PNG);
        // 换行与空白的粘贴也要能认。
        let wrapped = format!("  {}\n", encoded.chars().collect::<Vec<_>>().chunks(60)
            .map(|chunk| chunk.iter().collect::<String>())
            .collect::<Vec<_>>()
            .join("\n"));
        assert_eq!(decode_image_input(&wrapped).unwrap(), SAMPLE_PNG);
    }

    #[test]
    fn rejects_empty_and_broken_input() {
        assert_eq!(decode_image_input("   ").unwrap_err().code, "ocr_invalid_image");
        assert_eq!(decode_image_input("data:image/png,abc").unwrap_err().code, "ocr_invalid_image");
        assert_eq!(decode_image_input("不是图片@@@").unwrap_err().code, "ocr_invalid_image");
    }

    // user:“图像输入（用代码生成一张已知文字的图片，断言 OCR 结果包含该文字）”+
    // (样图是 PIL 画的白底黑字，仓库里就这一张，Rust 与 Python 测试共用)。
    #[cfg(windows)]
    #[test]
    fn recognizes_known_text_from_generated_image() {
        let available = platform::available_languages();
        match recognize(SAMPLE_PNG, None) {
            Ok(output) => {
                // 真实识别输出打出来，既当证据也方便对样式变化做肉眼比对。
                println!(
                    "[ocr] 语言={} 尺寸={}x{} 行数={} 文本={:?} 可用语言={:?}",
                    output.language,
                    output.image_width,
                    output.image_height,
                    output.lines.len(),
                    output.text,
                    output.available_languages,
                );
                assert!(!output.text.is_empty(), "这张样图里明明有字，识别结果不能是空的");
                for word in SAMPLE_WORDS {
                    assert!(
                        output.text.contains(word),
                        "识别结果里没有 {word}：{:?}",
                        output.text
                    );
                }
                assert!(!output.lines.is_empty(), "有文字就必须有行");
                assert!(!output.language.is_empty(), "要回报实际用的识别语言");
                assert!(output.image_width > 0 && output.image_height > 0);
            }
            // 没装语言包的机器上，这里要考的是「明确报缺包」而不是蒙混过关。
            Err(error) if error.code == "ocr_language_missing" => {
                assert!(available.is_empty(), "有语言包却报缺包，说明引擎创建有问题");
                assert!(error.message.contains("光学字符识别"), "缺包提示要告诉用户怎么装");
            }
            Err(error) => panic!("识别失败：{} {}", error.code, error.message),
        }
    }

    // user:“语言缺失错误”+(指定一个系统里肯定没有的语言，必须是缺包错误码，不能是空字符串)。
    #[cfg(windows)]
    #[test]
    fn missing_language_reports_explicit_code() {
        let error = recognize(SAMPLE_PNG, Some("zz-ZZ")).unwrap_err();
        assert_eq!(error.code, "ocr_language_missing");
        assert!(error.message.contains("zz-ZZ"));
    }

    // 坏图要给出明确的解码错误，而不是让系统异常穿到前端。
    #[cfg(windows)]
    #[test]
    fn broken_image_reports_invalid_image() {
        let error = recognize(b"definitely not an image", None).unwrap_err();
        assert_eq!(error.code, "ocr_invalid_image");
    }
}
