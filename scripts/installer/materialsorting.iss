; ============================================================================
; scripts/installer/materialsorting.iss — Inno Setup 中文安装包脚本（US-005，
; 权威 PRD：tasks/prd-local-deploy-freeze.md）。
;
; 由 scripts/build_freeze.py --installer（全量构建尾部第 7 步）或
; --installer-only（复用既有 dist 补打包）调用，版本经 ISCC /D 注入 —— 与
; Nuitka 冻结资源（--file-version/--file-description）同源版本串：
;   ISCC.exe /DMyAppVersion="0.1.0 g590375b dirty" ^
;            /DMyAppVersionNumber="0.1.0.319" ^
;            /DMyAppVersionFS="0.1.0-g590375b-dirty" ^
;            <repo>\scripts\installer\materialsorting.iss
; → dist\MaterialSorting-Setup-0.1.0-g590375b-dirty.exe
;
; 手工调试编译（三 define 均有 #ifndef 缺省占位）：
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" scripts\installer\materialsorting.iss
;
; 设计要点（PRD US-005 AC1 / 已定案决策③⑤⑦）：
;   - per-user 免 UAC：PrivilegesRequired=lowest + {localappdata}\Programs
;     安装目录（工厂机器常见无 admin）；
;   - 中文向导：单一语言 ChineseSimplified.isl（随仓 vendor —— Inno 官方发行
;     版不含中文；源 = github.com/jrsoftware/issrc tag is-6_7_3
;     Files/Languages/Unofficial/ChineseSimplified.isl，Inno ≥6.5 读无 BOM
;     UTF-8 .isl，上游维护 kira-96/Inno-Setup-Chinese-Simplified-Translation）；
;   - 升级 = 双击覆盖安装（PRD 定案⑤）：固定 AppId + UsePreviousAppDir（缺省
;     yes）记住目录；用户数据在 %LOCALAPPDATA%\MaterialSorting（安装目录外），
;     覆盖安装 / 卸载均不触碰；
;   - 卸载保留用户数据：无任何 [UninstallDelete] 破坏性条目 —— Inno 缺省只删
;     [Files] 装进去的文件，%LOCALAPPDATA%\MaterialSorting 天然幸存；
;   - 运行中检测（AC1「AppMutex 或等价」）：app 未做命名互斥体（v1 单实例 =
;     web_port.txt 健康探测，PRD 技术考虑留 v2 互斥体加固），故走 [Code]
;     tasklist 查镜像名等价实现（安装/卸载双向 + 安装前兜底复查）。
; ============================================================================

#define MyAppName "MaterialSorting"
#define MyAppNameCN "牛仔裤排料"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0-dev"
#endif
#ifndef MyAppVersionNumber
#define MyAppVersionNumber "0.0.0.0"
#endif
#ifndef MyAppVersionFS
#define MyAppVersionFS "0.0.0-dev"
#endif
#define MyAppExeName "MaterialSorting.exe"

[Setup]
; AppId 固定 GUID：升级识别同一应用（改动 = 升级断链 + 控制面板残留旧卸载项）
AppId={{ACDD30BC-6A3F-463F-96E7-EEA95B7CB366}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=MaterialSorting
UninstallDisplayName={#MyAppName}（{#MyAppNameCN}）
UninstallDisplayIcon={app}\{#MyAppExeName}
; per-user 免 UAC（PRD 定案③）—— 工厂机器常见无 admin
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
; 覆盖安装是标准升级动线（PRD 定案⑤），目录已存在不弹误报警告
DirExistsWarning=no
DisableProgramGroupPage=yes
; setup.exe 自身版本资源（数字四段限制 → 独立 define）
VersionInfoVersion={#MyAppVersionNumber}
VersionInfoCompany=MaterialSorting
VersionInfoProductName={#MyAppName} Workbench
VersionInfoDescription={#MyAppName} Setup
; 产物落仓库根 dist/（相对本 iss：scripts/installer/ → ../../dist）
OutputDir=..\..\dist
OutputBaseFilename=MaterialSorting-Setup-{#MyAppVersionFS}
; 单一中文语言 = 向导全程中文（不弹语言选择对话框）
ShowLanguageDialog=no
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0
; 运行检测走 [Code] tasklist（app 无命名互斥体），关掉重启管理器文件占用弹窗
CloseApplications=no
Uninstallable=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
; 桌面图标默认勾选（PRD：装完桌面即见图标；{cm:CreateDesktopIcon} 取自中文
; 语言包 = 「创建桌面快捷方式」）
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 冻结 onedir 整树（dist/MaterialSorting.dist/* → 安装目录）
Source: "..\..\dist\MaterialSorting.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}（{#MyAppNameCN}）"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}（{#MyAppNameCN}）"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 装完即用（中文「运行 MaterialSorting」；静默安装不自动拉起）
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; 故意无 [UninstallDelete]：卸载只删 [Files] 装入的文件，
; %LOCALAPPDATA%\MaterialSorting（上传母版/config_runs/状态文件）天然保留。

[Code]
// ------------------------------------------------------------ 运行中检测（等价）
// app 未做命名互斥体（v1 单实例 = web_port.txt 健康探测），AppMutex 依赖
// app 侧 CreateMutex —— 等价实现：tasklist 按镜像名探测（/FO CSV /NH 输出
// 无匹配时为提示行，不含镜像名不误报；镜像名纯 ASCII 免编码坑）。
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
  TmpFile: string;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}\ms_tasklist.txt');
  if Exec(ExpandConstant('{cmd}'),
       '/C tasklist /FI "IMAGENAME eq {#MyAppExeName}" /FO CSV /NH > "' + TmpFile + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringsFromFile(TmpFile, Lines) then
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Pos('{#MyAppExeName}', Lines[I]) > 0 then
          Result := True;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  while IsAppRunning() do
  begin
    // 静默安装（/SILENT /VERYSILENT）无界面接「重试/取消」—— 直接中止
    // （退出码 1），避免无头/批量部署挂死在看不见的对话框上
    if WizardSilent() then
    begin
      Log('检测到 MaterialSorting 正在运行：静默安装中止');
      Result := False;
      Break;
    end;
    // 「重试」= 重新探测（用户关掉黑窗后点它）；「取消」= 放弃安装
    if MsgBox('检测到 MaterialSorting 正在运行。' + #13#10 + #13#10 +
              '请先关闭其控制台窗口（或用任务管理器结束 MaterialSorting.exe 进程），' +
              '再点击「重试」继续安装。', mbConfirmation, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Break;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // 向导页停留期间的兜底复查：仍在运行 → 返回非空串 = 中止安装并展示该信息
  Result := '';
  if IsAppRunning() then
    Result := 'MaterialSorting 仍在运行，请先关闭其控制台窗口后重试。';
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while IsAppRunning() do
  begin
    if UninstallSilent() then
    begin
      Log('检测到 MaterialSorting 正在运行：静默卸载中止');
      Result := False;
      Break;
    end;
    if MsgBox('检测到 MaterialSorting 正在运行，无法卸载。' + #13#10 + #13#10 +
              '请先关闭其控制台窗口，再点击「重试」继续卸载。',
              mbConfirmation, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Break;
    end;
  end;
end;
