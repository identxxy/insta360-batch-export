#include <ins_stitcher.h>

#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {

struct Config {
    std::string input_path;
    std::string output_path;
    std::string model_root;
    std::string log_path;
    int output_width;
    int output_height;
    ins::STITCH_TYPE stitch_type;
    ins::ImageProcessingAccel image_processing_accel;
    bool enable_flowstate;
    bool enable_denoise;
    bool enable_directionlock;
    bool enable_cuda;
    bool help;
    int timeout_seconds;

    Config()
        : output_width(3840),
          output_height(1920),
          stitch_type(ins::STITCH_TYPE::OPTFLOW),
          image_processing_accel(ins::ImageProcessingAccel::kAuto),
          enable_flowstate(true),
          enable_denoise(true),
          enable_directionlock(false),
          enable_cuda(true),
          help(false),
          timeout_seconds(21600) {}
};

struct StitchResult {
    bool finished;
    bool has_error;
    int sdk_error;
    std::string error_info;
    int progress;

    StitchResult()
        : finished(false), has_error(false), sdk_error(0), progress(-1) {}
};

void PrintUsage(std::ostream& os) {
    os << "Usage:\n"
       << "  insta_media_exporter --input <video.insv> --output <video.mp4> "
       << "--model-root <models_dir> [options]\n\n"
       << "Required:\n"
       << "  --input <path>                 Input .insv file. Exactly one input per run.\n"
       << "  --output <path>                Output .mp4 file.\n"
       << "  --model-root <path>            MediaSDK model root. If omitted, uses "
       << "INSTA_MEDIA_MODELS_DIR.\n\n"
       << "Options:\n"
       << "  --output-size <WxH>            Output panorama size. Default: 3840x1920.\n"
       << "  --stitch-type <name>           optflow|dynamicstitch|template|aistitch. "
       << "Default: optflow.\n"
       << "  --enable-flowstate             Enable FlowState. Default: on.\n"
       << "  --enable-denoise               Enable denoise. Default: on.\n"
       << "  --enable-directionlock         Enable direction lock. Default: off.\n"
       << "  --disable-cuda                 Disable CUDA. Default: CUDA on.\n"
       << "  --image-processing-accel <v>   auto|cpu. Default: auto.\n"
       << "  --timeout-seconds <seconds>    Cancel stalled export after this many seconds. "
       << "Default: 21600.\n"
       << "  --log-path <path>              MediaSDK log path.\n"
       << "  --help                         Print this help.\n";
}

bool IsOption(const char* arg) {
    return arg != NULL && std::string(arg).find("--") == 0;
}

bool NeedValue(int argc, char** argv, int index, const std::string& option,
               std::string* error) {
    if (index + 1 >= argc || IsOption(argv[index + 1])) {
        *error = option + " requires a value";
        return false;
    }
    return true;
}

bool ParsePositiveInt(const std::string& text, int* value) {
    if (text.empty()) {
        return false;
    }

    char* end = NULL;
    errno = 0;
    long parsed = std::strtol(text.c_str(), &end, 10);
    if (errno != 0 || end == text.c_str() || *end != '\0' || parsed <= 0 ||
        parsed > 100000) {
        return false;
    }

    *value = static_cast<int>(parsed);
    return true;
}

bool ParseOutputSize(const std::string& text, int* width, int* height) {
    std::size_t x_pos = text.find('x');
    if (x_pos == std::string::npos) {
        x_pos = text.find('X');
    }
    if (x_pos == std::string::npos || x_pos == 0 || x_pos + 1 >= text.size()) {
        return false;
    }

    int parsed_width = 0;
    int parsed_height = 0;
    if (!ParsePositiveInt(text.substr(0, x_pos), &parsed_width) ||
        !ParsePositiveInt(text.substr(x_pos + 1), &parsed_height)) {
        return false;
    }

    *width = parsed_width;
    *height = parsed_height;
    return true;
}

bool ParseStitchType(const std::string& text, ins::STITCH_TYPE* stitch_type) {
    if (text == "optflow") {
        *stitch_type = ins::STITCH_TYPE::OPTFLOW;
        return true;
    }
    if (text == "dynamicstitch") {
        *stitch_type = ins::STITCH_TYPE::DYNAMICSTITCH;
        return true;
    }
    if (text == "template") {
        *stitch_type = ins::STITCH_TYPE::TEMPLATE;
        return true;
    }
    if (text == "aistitch") {
        *stitch_type = ins::STITCH_TYPE::AIFLOW;
        return true;
    }
    return false;
}

bool ParseImageProcessingAccel(
    const std::string& text,
    ins::ImageProcessingAccel* image_processing_accel) {
    if (text == "auto") {
        *image_processing_accel = ins::ImageProcessingAccel::kAuto;
        return true;
    }
    if (text == "cpu") {
        *image_processing_accel = ins::ImageProcessingAccel::kCPU;
        return true;
    }
    return false;
}

bool EndsWith(const std::string& text, const std::string& suffix) {
    return text.size() >= suffix.size() &&
           text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool FileExists(const std::string& path) {
    struct stat st;
    return ::stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

bool DirExists(const std::string& path) {
    struct stat st;
    return ::stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

std::string ParentDir(const std::string& path) {
    std::size_t slash_pos = path.find_last_of('/');
    if (slash_pos == std::string::npos) {
        return ".";
    }
    if (slash_pos == 0) {
        return "/";
    }
    return path.substr(0, slash_pos);
}

bool MakeDirs(const std::string& dir, std::string* error) {
    if (dir.empty() || dir == ".") {
        return true;
    }
    if (DirExists(dir)) {
        return true;
    }

    std::string current;
    std::size_t index = 0;
    if (dir[0] == '/') {
        current = "/";
        index = 1;
    }

    while (index <= dir.size()) {
        std::size_t slash_pos = dir.find('/', index);
        std::string part = dir.substr(
            index, slash_pos == std::string::npos ? std::string::npos
                                                   : slash_pos - index);
        if (!part.empty()) {
            if (!current.empty() && current[current.size() - 1] != '/') {
                current += "/";
            }
            current += part;

            if (!DirExists(current)) {
                if (::mkdir(current.c_str(), 0755) != 0) {
                    if (errno == EEXIST) {
                        *error = "path exists but is not a directory: " + current;
                        return false;
                    }
                    *error = "failed to create directory " + current + ": " +
                             std::strerror(errno);
                    return false;
                }
            }
        }

        if (slash_pos == std::string::npos) {
            break;
        }
        index = slash_pos + 1;
    }

    if (!DirExists(dir)) {
        *error = "path exists but is not a directory: " + dir;
        return false;
    }
    return true;
}

std::string GetEnvOrEmpty(const char* name) {
    const char* value = std::getenv(name);
    return value == NULL ? std::string() : std::string(value);
}

bool ParseArgs(int argc, char** argv, Config* config, std::string* error) {
    for (int i = 1; i < argc; ++i) {
        std::string arg(argv[i]);

        if (arg == "--help") {
            config->help = true;
            continue;
        }
        if (arg == "--input") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!config->input_path.empty()) {
                *error = "--input may only be supplied once";
                return false;
            }
            config->input_path = argv[++i];
            continue;
        }
        if (arg == "--output") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!config->output_path.empty()) {
                *error = "--output may only be supplied once";
                return false;
            }
            config->output_path = argv[++i];
            continue;
        }
        if (arg == "--model-root") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            config->model_root = argv[++i];
            continue;
        }
        if (arg == "--output-size") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!ParseOutputSize(argv[++i], &config->output_width,
                                 &config->output_height)) {
                *error = "--output-size must be formatted as positive WxH";
                return false;
            }
            continue;
        }
        if (arg == "--stitch-type") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!ParseStitchType(argv[++i], &config->stitch_type)) {
                *error = "--stitch-type must be optflow, dynamicstitch, "
                         "template, or aistitch";
                return false;
            }
            continue;
        }
        if (arg == "--enable-flowstate") {
            config->enable_flowstate = true;
            continue;
        }
        if (arg == "--enable-denoise") {
            config->enable_denoise = true;
            continue;
        }
        if (arg == "--enable-directionlock") {
            config->enable_directionlock = true;
            config->enable_flowstate = true;
            continue;
        }
        if (arg == "--disable-cuda") {
            config->enable_cuda = false;
            continue;
        }
        if (arg == "--image-processing-accel") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!ParseImageProcessingAccel(argv[++i],
                                           &config->image_processing_accel)) {
                *error = "--image-processing-accel must be auto or cpu";
                return false;
            }
            continue;
        }
        if (arg == "--timeout-seconds") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            if (!ParsePositiveInt(argv[++i], &config->timeout_seconds)) {
                *error = "--timeout-seconds must be a positive integer";
                return false;
            }
            continue;
        }
        if (arg == "--log-path") {
            if (!NeedValue(argc, argv, i, arg, error)) {
                return false;
            }
            config->log_path = argv[++i];
            continue;
        }

        *error = "unknown option: " + arg;
        return false;
    }

    if (config->help) {
        return true;
    }

    if (config->input_path.empty()) {
        *error = "--input is required";
        return false;
    }
    if (config->output_path.empty()) {
        *error = "--output is required";
        return false;
    }
    if (config->model_root.empty()) {
        config->model_root = GetEnvOrEmpty("INSTA_MEDIA_MODELS_DIR");
    }
    if (config->model_root.empty()) {
        *error = "--model-root is required when INSTA_MEDIA_MODELS_DIR is not set";
        return false;
    }

    if (!EndsWith(config->input_path, ".insv") &&
        !EndsWith(config->input_path, ".INSV")) {
        *error = "--input must point to a .insv file";
        return false;
    }
    if (!EndsWith(config->output_path, ".mp4") &&
        !EndsWith(config->output_path, ".MP4")) {
        *error = "--output must point to a .mp4 file";
        return false;
    }
    if (!FileExists(config->input_path)) {
        *error = "input file does not exist or is not a regular file: " +
                 config->input_path;
        return false;
    }
    if (!DirExists(config->model_root)) {
        *error = "model root does not exist or is not a directory: " +
                 config->model_root;
        return false;
    }

    return true;
}

std::string StitchTypeName(ins::STITCH_TYPE stitch_type) {
    switch (stitch_type) {
        case ins::STITCH_TYPE::OPTFLOW:
            return "optflow";
        case ins::STITCH_TYPE::DYNAMICSTITCH:
            return "dynamicstitch";
        case ins::STITCH_TYPE::TEMPLATE:
            return "template";
        case ins::STITCH_TYPE::AIFLOW:
            return "aistitch";
    }
    return "unknown";
}

std::string AccelName(ins::ImageProcessingAccel accel) {
    return accel == ins::ImageProcessingAccel::kCPU ? "cpu" : "auto";
}

int RunStitch(const Config& config) {
    std::string error;
    if (!MakeDirs(ParentDir(config.output_path), &error)) {
        std::cerr << "error: " << error << std::endl;
        return 2;
    }
    if (!config.log_path.empty() && !MakeDirs(ParentDir(config.log_path), &error)) {
        std::cerr << "error: " << error << std::endl;
        return 2;
    }

    if (!config.log_path.empty()) {
        ins::SetLogPath(config.log_path);
    }
    ins::SetLogLevel(ins::InsLogLevel::ERR);
    ins::InitEnv();
    ins::SetModelFileRootDir(config.model_root);

    std::vector<std::string> input_paths;
    input_paths.push_back(config.input_path);

    std::mutex mutex;
    std::condition_variable cond;
    StitchResult result;

    std::shared_ptr<ins::VideoStitcher> video_stitcher(new ins::VideoStitcher());
    video_stitcher->SetInputPath(input_paths);
    video_stitcher->SetOutputPath(config.output_path);
    video_stitcher->SetStitchType(config.stitch_type);
    video_stitcher->EnableCuda(config.enable_cuda);
    video_stitcher->SetImageProcessingAccelType(config.image_processing_accel);
    video_stitcher->SetOutputSize(config.output_width, config.output_height);
    video_stitcher->EnableFlowState(config.enable_flowstate);
    video_stitcher->EnableDenoise(config.enable_denoise);
    video_stitcher->EnableDirectionLock(config.enable_directionlock);

    video_stitcher->SetStitchProgressCallback(
        [&](int process, int callback_error) {
            std::unique_lock<std::mutex> lock(mutex);
            if (callback_error != 0) {
                result.has_error = true;
                result.sdk_error = callback_error;
                result.error_info = "progress callback reported error " +
                                    std::to_string(callback_error);
                cond.notify_one();
                return;
            }

            if (result.progress != process) {
                result.progress = process;
                std::cout << "progress=" << process << std::endl;
            }

            if (process >= 100) {
                result.finished = true;
                cond.notify_one();
            }
        });

    video_stitcher->SetStitchStateCallback(
        [&](int callback_error, const char* err_info) {
            std::unique_lock<std::mutex> lock(mutex);
            result.has_error = true;
            result.sdk_error = callback_error;
            result.error_info = err_info == NULL ? std::string()
                                                 : std::string(err_info);
            cond.notify_one();
        });

    std::cout << "start input=" << config.input_path
              << " output=" << config.output_path
              << " size=" << config.output_width << "x" << config.output_height
              << " stitch_type=" << StitchTypeName(config.stitch_type)
              << " flowstate=" << (config.enable_flowstate ? "on" : "off")
              << " denoise=" << (config.enable_denoise ? "on" : "off")
              << " directionlock=" << (config.enable_directionlock ? "on" : "off")
              << " cuda=" << (config.enable_cuda ? "on" : "off")
              << " image_processing_accel="
              << AccelName(config.image_processing_accel)
              << " timeout_seconds=" << config.timeout_seconds << std::endl;

    const std::chrono::steady_clock::time_point start_time =
        std::chrono::steady_clock::now();
    try {
        video_stitcher->StartStitch();
    } catch (const std::exception& ex) {
        std::cerr << "error: StartStitch threw exception: " << ex.what()
                  << std::endl;
        return 3;
    } catch (...) {
        std::cerr << "error: StartStitch threw unknown exception" << std::endl;
        return 3;
    }

    bool timed_out = false;
    {
        std::unique_lock<std::mutex> lock(mutex);
        const std::chrono::steady_clock::time_point deadline =
            start_time + std::chrono::seconds(config.timeout_seconds);
        timed_out = !cond.wait_until(
            lock, deadline, [&] { return result.finished || result.has_error; });
    }

    const std::chrono::steady_clock::time_point end_time =
        std::chrono::steady_clock::now();
    const double seconds =
        std::chrono::duration_cast<std::chrono::duration<double> >(
            end_time - start_time).count();

    if (timed_out) {
        try {
            video_stitcher->CancelStitch();
        } catch (const std::exception& ex) {
            std::cerr << "warning: CancelStitch threw exception: " << ex.what()
                      << std::endl;
        } catch (...) {
            std::cerr << "warning: CancelStitch threw unknown exception"
                      << std::endl;
        }
        std::cerr << "error: stitch timed out after "
                  << config.timeout_seconds << " seconds" << std::endl;
        std::cerr << "elapsed_seconds=" << seconds << std::endl;
        return 124;
    }

    if (result.has_error) {
        std::cerr << "error: stitch failed sdk_error=" << result.sdk_error
                  << " message=" << result.error_info << std::endl;
        std::cerr << "elapsed_seconds=" << seconds << std::endl;
        return 10;
    }

    std::cout << "done output=" << config.output_path
              << " elapsed_seconds=" << seconds << std::endl;
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    Config config;
    std::string error;

    if (!ParseArgs(argc, argv, &config, &error)) {
        std::cerr << "error: " << error << std::endl;
        PrintUsage(std::cerr);
        return 2;
    }

    if (config.help) {
        PrintUsage(std::cout);
        return 0;
    }

    return RunStitch(config);
}
