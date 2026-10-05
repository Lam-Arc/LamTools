/**
 * 资料库/应用图标：从 lucide 迁到 IconPark 的名称映射。
 *
 * 左列是现在代码里用的 lucide 名，右列是 IconPark（@icon-park/vue-next）的组件名。
 * 命名体系完全不同（lucide 的 `House` 在 IconPark 叫 `Home`、`X` 叫 `Close`、
 * `Settings` 叫 `Config`），所以这张表是迁移的唯一依据，改一处就在这里改。
 *
 * 标注 `// 语义有偏移` 的条目：IconPark 没有同义图形，取的是最接近的一个，
 * 形状会变、指代也会略微移动，需要人眼确认。
 */

export const ICONPARK_MAP: Record<string, string> = {
  Activity: 'ActivitySource',
  AppWindow: 'Application',
  Archive: 'Inbox', // 语义有偏移
  ArrowDown: 'Down',
  ArrowDownToLine: 'Download',
  ArrowLeft: 'Left',
  ArrowRight: 'Right',
  ArrowUp: 'Up',
  Bell: 'Remind', // 语义有偏移
  Blocks: 'Components', // 语义有偏移
  BookOpen: 'BookOpen',
  Bookmark: 'Bookmark',
  Bot: 'Robot',
  Box: 'Box',
  Braces: 'CodeBrackets',
  Brain: 'Brain',
  BriefcaseBusiness: 'Briefcase',
  Brush: 'FormatBrush', // 语义有偏移
  CalendarClock: 'Calendar',
  Camera: 'Camera',
  ChartNoAxesCombined: 'Analysis',
  Check: 'Check',
  ChevronDown: 'Down',
  ChevronLeft: 'Left',
  ChevronRight: 'Right',
  ChevronUp: 'Up',
  Circle: 'Round', // 语义有偏移
  CircleAlert: 'Attention',
  CircleCheck: 'CheckOne',
  CircleHelp: 'Help',
  ClipboardPaste: 'Clipboard',
  Clock: 'Time',
  Clock3: 'Time',
  Code2: 'Code',
  Copy: 'Copy',
  Database: 'Data',
  ExternalLink: 'LinkOut',
  Eye: 'PreviewOpen',
  EyeOff: 'PreviewClose',
  File: 'FileText',
  FileArchive: 'FolderMinus', // 语义有偏移
  FileCode2: 'FileCode',
  FileDown: 'Download',
  FileImage: 'ImageFiles', // 语义有偏移
  FileJson2: 'CodeBrackets', // 语义有偏移
  FilePenLine: 'Edit',
  FilePlus2: 'FileAddition',
  FileSpreadsheet: 'FileExcel',
  FileText: 'FileText',
  FileUp: 'Upload',
  Film: 'Film',
  Folder: 'Folder',
  FolderKanban: 'CollectionFiles', // 语义有偏移
  FolderOpen: 'FolderOpen',
  FolderSearch: 'FolderSearch',
  Gauge: 'Dashboard', // 语义有偏移
  GitBranch: 'Branch',
  GitFork: 'Branch',
  Globe: 'Earth',
  Globe2: 'Earth',
  Goal: 'Target',
  GripVertical: 'Drag',
  History: 'History',
  Hourglass: 'Hourglass',
  House: 'Home',
  Image: 'Picture',
  Inbox: 'Inbox',
  Info: 'Info',
  Languages: 'Translate',
  Layers: 'Layers',
  LayoutGrid: 'GridFour', // 语义有偏移
  LayoutList: 'List',
  Library: 'BookOne',
  Lightbulb: 'Light',
  List: 'List',
  ListChecks: 'Checklist',
  ListTodo: 'ListCheckbox',
  ListTree: 'TreeList',
  LoaderCircle: 'Loading',
  Lock: 'Lock',
  LockKeyhole: 'Lock',
  Maximize2: 'FullScreen',
  MessageCircle: 'Comment',
  MessageSquare: 'Message',
  MessageSquarePlus: 'MessageSent', // 语义有偏移
  MessageSquareText: 'MessageOne',
  Minimize2: 'OffScreen', // 语义有偏移
  Minus: 'Minus',
  Monitor: 'Monitor',
  MonitorPlay: 'Video',
  MonitorSmartphone: 'Computer',
  Moon: 'Moon',
  MoreHorizontal: 'More',
  Music: 'Music',
  Package: 'Cube', // 语义有偏移
  Palette: 'ColorCard',
  PanelLeft: 'LeftBar', // 语义有偏移
  PanelRight: 'RightBar', // 语义有偏移
  Paperclip: 'Paperclip',
  PawPrint: 'Cat', // 语义有偏移
  Pencil: 'Edit',
  Pin: 'Pin',
  PinOff: 'Close',
  Plug: 'Plug',
  Plus: 'Add',
  Power: 'Power',
  PowerOff: 'Power',
  Presentation: 'DataScreen', // 语义有偏移
  Puzzle: 'Puzzle',
  Quote: 'Quote',
  Radar: 'Radar',
  RefreshCw: 'Refresh',
  Rocket: 'Rocket',
  RotateCcw: 'Undo',
  RotateCw: 'Redo',
  Save: 'Save',
  Scale: 'Balance', // 语义有偏移
  Scissors: 'Scissors',
  Search: 'Search',
  Send: 'Send',
  Server: 'Server',
  Settings: 'Config', // 语义有偏移
  Settings2: 'Config',
  Share2: 'Share',
  Sheet: 'DataSheet',
  ShieldCheck: 'Protect', // 语义有偏移
  SlidersHorizontal: 'Equalizer', // 语义有偏移
  Smartphone: 'Phone',
  Sparkles: 'Magic', // 语义有偏移
  Square: 'Square',
  SquareTerminal: 'Terminal',
  Star: 'Star',
  Sun: 'Sun',
  Sunrise: 'SunOne',
  Table2: 'InsertTable',
  Target: 'Target',
  Terminal: 'Terminal',
  TextSelect: 'Text', // 语义有偏移
  ToggleLeft: 'Switch', // 语义有偏移
  ToggleRight: 'Switch', // 语义有偏移
  Trash2: 'Delete',
  TriangleAlert: 'Caution',
  Undo2: 'Undo',
  UnlockKeyhole: 'Unlock',
  Upload: 'Upload',
  UserRound: 'User',
  UserRoundPlus: 'AddUser',
  UsersRound: 'Peoples',
  Video: 'Video',
  Wand2: 'MagicWand',
  Webhook: 'Api', // 语义有偏移
  Wrench: 'Tool',
  X: 'Close', // 语义有偏移
}

/** 语义有偏移、需要确认的条目（形状不同，不只是改名）。 */
export const ICONPARK_SHIFTED: string[] = [
  'Archive',
  'Bell',
  'Blocks',
  'Brush',
  'Circle',
  'FileArchive',
  'FileImage',
  'FileJson2',
  'FolderKanban',
  'Gauge',
  'LayoutGrid',
  'MessageSquarePlus',
  'Minimize2',
  'Package',
  'PanelLeft',
  'PanelRight',
  'PawPrint',
  'Presentation',
  'Scale',
  'Settings',
  'ShieldCheck',
  'SlidersHorizontal',
  'Sparkles',
  'TextSelect',
  'ToggleLeft',
  'ToggleRight',
  'Webhook',
  'X',
]
