#!/bin/bash
#===============================================================================
# WingTrace 一键部署脚本 - TUI 界面模块
#===============================================================================

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# TUI 颜色主题
TUI_BG="\033[44m"
TUI_FG="\033[37m"
TUI_HIGHLIGHT="\033[33m"
TUI_SELECTED="\033[46m"
TUI_BORDER="━"

#===============================================================================
# 显示主菜单
#===============================================================================
show_main_menu() {
    clear
    echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}      ${WHITE}🪶  羽迹 WingTrace 一键部署${NC}            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    ${GREEN}AI 驱动的鸟类照片智能管理系统${NC}           ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"

    local options=(
        "🚀  开始部署"
        "⚙️  配置选项"
        "📦  更新项目"
        "⬇️  下载模型"
        "▶️  启动服务"
        "📖  查看帮助"
        "❌  退出"
    )

    for i in "${!options[@]}"; do
        local idx=$((i + 1))
        local opt="${options[$i]}"
        local padding=$(printf '%*s' $((40 - ${#opt} - 6)) "")
        echo -e "${CYAN}┃${NC}    [${idx}] $opt${padding}${CYAN}┃${NC}"
    done

    echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
    echo ""
    echo -e -n "${CYAN}> 请输入选项 (1-${#options[@]}): ${NC}"
}

#===============================================================================
# 显示状态栏
#===============================================================================
show_status_bar() {
    local status="$1"
    local py_ver=$(python3 --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' || echo "未安装")
    local git_ver=$(git --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || echo "未安装")

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}┃${NC}  Python: ${WHITE}$py_ver${NC}    Git: ${WHITE}$git_ver${NC}    状态: ${WHITE}$status${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

#===============================================================================
# 显示配置菜单
#===============================================================================
show_config_menu() {
    clear
    echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}      ${WHITE}⚙️  配置选项${NC}                          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"

    local options=(
        "📁 设置照片源目录"
        "📁 设置输出目录"
        "🖥️  设置处理设备"
        "🌐 配置代理"
        "📋 查看当前配置"
        "🔧 生成配置文件"
        "↩️  返回主菜单"
    )

    for i in "${!options[@]}"; do
        local idx=$((i + 1))
        local opt="${options[$i]}"
        local padding=$(printf '%*s' $((40 - ${#opt} - 6)) "")
        echo -e "${CYAN}┃${NC}    [${idx}] $opt${padding}${CYAN}┃${NC}"
    done

    echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
    echo ""
    echo -e -n "${CYAN}> 请输入选项 (1-${#options[@]}): ${NC}"
}

#===============================================================================
# 显示服务菜单
#===============================================================================
show_service_menu() {
    clear
    echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}      ${WHITE}▶️  启动服务${NC}                           ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"

    local options=(
        "🌐 启动 Web 界面 (浏览器管理)"
        "🔄 启动照片处理流水线"
        "📊 查看服务状态"
        "🧪 运行测试"
        "↩️  返回主菜单"
    )

    for i in "${!options[@]}"; do
        local idx=$((i + 1))
        local opt="${options[$i]}"
        local padding=$(printf '%*s' $((40 - ${#opt} - 6)) "")
        echo -e "${CYAN}┃${NC}    [${idx}] $opt${padding}${CYAN}┃${NC}"
    done

    echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
    echo ""
    echo -e -n "${CYAN}> 请输入选项 (1-${#options[@]}): ${NC}"
}

#===============================================================================
# 显示帮助信息
#===============================================================================
show_help() {
    clear
    echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}      ${WHITE}📖  使用帮助${NC}                          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}  ${WHITE}羽迹${NC} 是一款 AI 驱动的鸟类照片管理系统          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}  ${WHITE}主要功能:${NC}                                        ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    • YOLOv8 鸟类检测                             ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    • BioCLIP 物种智能识别                        ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    • 自动元数据注入 (EXIF/IPTC)                  ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    • Web 界面浏览和管理                          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"
    echo -e "${CYAN}┃${NC}  ${WHITE}快速开始:${NC}                                        ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    1. 选择 [开始部署] 安装依赖                   ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    2. 选择 [配置选项] 设置照片目录               ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    3. 选择 [启动服务] → [启动 Web 界面]          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    4. 浏览器访问 http://localhost:8000           ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"
    echo -e "${CYAN}┃${NC}  ${WHITE}目录结构要求:${NC}                                     ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}    📁 年/                                  ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}       └── yyyyMMdd_地点/                    ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}          └── *.jpg/*.png                    ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
    echo ""
    pause "按 Enter 返回主菜单..."
}

#===============================================================================
# 显示配置摘要
#===============================================================================
show_config_summary() {
    clear
    echo -e "${CYAN}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}      ${WHITE}📋 当前配置${NC}                          ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"

    # 加载配置
    init_config_dir

    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┃${NC}  照片源目录:    ${WHITE}${SOURCE_DIR:-未配置}${NC}"
    echo -e "${CYAN}┃${NC}  输出目录:      ${WHITE}${OUTPUT_DIR:-未配置}${NC}"
    echo -e "${CYAN}┃${NC}  处理设备:      ${WHITE}${DEVICE:-未配置}${NC}"
    echo -e "${CYAN}┃${NC}  代理:          ${WHITE}${PROXY:-无}${NC}"
    echo -e "${CYAN}┃${NC}  Gitee 镜像:    ${WHITE}${GITEE_MIRROR:-未配置}${NC}"
    echo -e "${CYAN}┃${NC}  PyPI 镜像:     ${WHITE}${PIP_MIRROR:-未配置}${NC}"
    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"

    if [ "$CONFIGURED" = "1" ]; then
        echo -e "${CYAN}┃${NC}         ${GREEN}✓ 配置已完成${NC}                            ${CYAN}┃${NC}"
    else
        echo -e "${CYAN}┃${NC}         ${YELLOW}⚠ 需要配置${NC}                             ${CYAN}┃${NC}"
    fi

    echo -e "${CYAN}┃${NC}                                            ${CYAN}┃${NC}"
    echo -e "${CYAN}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
    echo ""
    pause "按 Enter 返回..."
}

#===============================================================================
# 显示进度条
#===============================================================================
show_progress_bar() {
    local current=$1
    local total=$2
    local title="${3:-进度}"

    local percent=$((current * 100 / total))
    local width=30
    local filled=$((width * current / total))
    local empty=$((width - filled))

    printf "\r${CYAN}${title}:${NC} ["
    printf '%*s' "$filled" '' | tr ' ' '█'
    printf '%*s' "$empty" '' | tr ' ' '░'
    printf "] %d%%" "$percent"
}

#===============================================================================
# 确认对话框
#===============================================================================
confirm_dialog() {
    local message="$1"
    local default="${2:-y}"

    while true; do
        echo -e "\n${CYAN}$message${NC}"

        if [ "$default" = "y" ]; then
            echo -n "[Y/n] > "
        else
            echo -n "[y/N] > "
        fi

        read -r answer
        answer=$(echo "$answer" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

        if [ -z "$answer" ]; then
            answer="$default"
        fi

        case "$answer" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
        esac
    done
}

#===============================================================================
# 输入对话框
#===============================================================================
input_dialog() {
    local prompt="$1"
    local default="$2"
    local password="${3:-false}"

    if [ "$password" = "true" ]; then
        echo -n "$prompt: "
        stty -echo
        read -r input
        stty echo
        echo ""
    else
        if [ -n "$default" ]; then
            echo -n "$prompt [$default]: "
        else
            echo -n "$prompt: "
        fi
        read -r input
        input=$(echo "$input" | tr -d '\r\n')
    fi

    if [ -z "$input" ] && [ -n "$default" ]; then
        echo "$default"
    else
        echo "$input"
    fi
}

#===============================================================================
# 选择对话框
#===============================================================================
select_dialog() {
    local title="$1"
    shift
    local options=("$@")
    local num_options=${#options[@]}

    echo -e "\n${CYAN}$title${NC}\n"

    for i in "${!options[@]}"; do
        local idx=$((i + 1))
        echo "  $idx) ${options[$i]}"
    done

    echo ""
    echo -n "请选择 (1-$num_options): "

    while true; do
        read -r choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$num_options" ]; then
            return $((choice - 1))
        fi
        echo -n "无效选择，请重新输入: "
    done
}

#===============================================================================
# 消息框
#===============================================================================
message_box() {
    local title="$1"
    local message="$2"
    local type="${3:-info}"

    local color="$CYAN"
    case "$type" in
        success) color="$GREEN" ;;
        error)   color="$RED" ;;
        warning) color="$YELLOW" ;;
    esac

    clear
    echo -e "${color}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${NC}"
    echo -e "${color}┃${NC}  $title"
    echo -e "${color}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫${NC}"
    echo -e "${color}┃${NC}"
    echo -e "${color}┃${NC}  $message"
    echo -e "${color}┃${NC}"
    echo -e "${color}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}"
}

#===============================================================================
# 运行 TUI 主循环
#===============================================================================
run_tui() {
    # 检查是否支持 TUI
    if [ ! -t 1 ]; then
        log_warn "终端不支持 TUI，使用命令行模式"
        return 1
    fi

    # 初始化
    init_config_dir
    detect_environment

    while true; do
        show_main_menu
        read -r choice

        if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
            log_error "无效输入"
            sleep 1
            continue
        fi

        case $choice in
            1)  # 开始部署
                run_deploy_tui
                ;;
            2)  # 配置选项
                run_config_tui
                ;;
            3)  # 更新项目
                run_update_tui
                ;;
            4)  # 下载模型
                run_download_model_tui
                ;;
            5)  # 启动服务
                run_service_tui
                ;;
            6)  # 帮助
                show_help
                ;;
            7)  # 退出
                echo ""
                log_info "感谢使用羽迹！再见！"
                exit 0
                ;;
            *)
                log_error "无效选项"
                sleep 1
                ;;
        esac
    done
}

#===============================================================================
# 部署 TUI
#===============================================================================
run_deploy_tui() {
    message_box "🚀 开始部署" "正在检测环境..." "info"

    # 检测环境
    detect_environment

    message_box "🚀 开始部署" "环境检测完成，开始安装依赖..." "info"

    # 安装依赖
    source "${SCRIPT_DIR}/install.sh"
    install_all_dependencies

    # 运行配置向导
    message_box "🚀 开始部署" "依赖安装完成，现在配置项目..." "info"

    source "${SCRIPT_DIR}/config.sh"
    run_config_wizard

    pause "按 Enter 返回主菜单..."
}

#===============================================================================
# 配置 TUI
#===============================================================================
run_config_tui() {
    while true; do
        show_config_menu
        read -r choice

        if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
            continue
        fi

        case $choice in
            1)
                source "${SCRIPT_DIR}/config.sh"
                config_source_dir
                ;;
            2)
                source "${SCRIPT_DIR}/config.sh"
                config_output_dir
                ;;
            3)
                source "${SCRIPT_DIR}/config.sh"
                config_device
                ;;
            4)
                source "${SCRIPT_DIR}/config.sh"
                config_proxy
                ;;
            5)
                show_config_summary
                ;;
            6)
                source "${SCRIPT_DIR}/config.sh"
                generate_settings_yaml
                generate_secrets_yaml
                log_success "配置文件已生成"
                pause "按 Enter 继续..."
                ;;
            7)
                return 0
                ;;
        esac
    done
}

#===============================================================================
# 更新 TUI
#===============================================================================
run_update_tui() {
    message_box "📦 更新项目" "正在更新..." "info"

    source "${SCRIPT_DIR}/clone.sh"
    clone_project

    if [ $? -eq 0 ]; then
        message_box "📦 更新项目" "项目已更新到最新版本！" "success"
    else
        message_box "📦 更新项目" "更新失败，请检查网络连接" "error"
    fi

    pause "按 Enter 返回..."
}

#===============================================================================
# 下载模型 TUI
#===============================================================================
run_download_model_tui() {
    message_box "⬇️ 下载模型" "正在下载 BioCLIP 模型 (~500MB)..." "info"

    source "${SCRIPT_DIR}/clone.sh"
    download_model

    if [ $? -eq 0 ]; then
        message_box "⬇️ 下载模型" "模型下载完成！" "success"
    else
        message_box "⬇️ 下载模型" "模型下载失败，请稍后重试" "error"
    fi

    pause "按 Enter 返回..."
}

#===============================================================================
# 服务 TUI
#===============================================================================
run_service_tui() {
    while true; do
        show_service_menu
        read -r choice

        if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
            continue
        fi

        case $choice in
            1)  # 启动 Web 界面
                message_box "🌐 启动 Web 界面" "启动中..." "info"
                cd "$PROJECT_ROOT"
                if [ -f "${PROJECT_ROOT}/venv/Scripts/python" ]; then
                    "${PROJECT_ROOT}/venv/Scripts/python" "${PROJECT_ROOT}/src/web/app.py"
                else
                    python3 "${PROJECT_ROOT}/src/web/app.py"
                fi
                ;;
            2)  # 启动流水线
                message_box "🔄 启动流水线" "请在命令行中运行:\n\n  python src/pipeline_runner.py --start 20240101" "info"
                pause "按 Enter 返回..."
                ;;
            3)  # 服务状态
                message_box "📊 服务状态" "Web 服务: http://localhost:8000\n\n请确保已运行 [启动服务] 选项" "info"
                pause "按 Enter 返回..."
                ;;
            4)  # 运行测试
                message_box "🧪 运行测试" "正在运行测试..." "info"
                cd "$PROJECT_ROOT"
                python3 -m pytest tests/ -v 2>/dev/null || log_warn "测试失败或未找到测试"
                pause "按 Enter 返回..."
                ;;
            5)  # 返回
                return 0
                ;;
        esac
    done
}
