#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef int (*fn_iotc_init)(unsigned short);
typedef int (*fn_get_sid)(void);
typedef int (*fn_connect)(const char *, int);
typedef void (*fn_session_close)(int);
typedef int (*fn_deinit)(void);
typedef int (*fn_stop_sid)(int);
typedef int (*fn_rdt_init)(void);
typedef int (*fn_rdt_create)(int, int, unsigned char);
typedef int (*fn_rdt_write)(int, const char *, int);
typedef int (*fn_rdt_read)(int, char *, int, int);
typedef int (*fn_rdt_destroy)(int);
typedef int (*fn_rdt_deinit)(void);

struct connect_ctx {
    fn_connect fn;
    const char *uid;
    int sid;
    volatile int done;
    int code;
};

static void *connect_worker(void *pointer) {
    struct connect_ctx *ctx = (struct connect_ctx *)pointer;
    ctx->code = ctx->fn(ctx->uid, ctx->sid);
    ctx->done = 1;
    return NULL;
}

static long monotonic_ms(void) {
    struct timespec timestamp;
    clock_gettime(CLOCK_MONOTONIC, &timestamp);
    return timestamp.tv_sec * 1000L + timestamp.tv_nsec / 1000000L;
}

static void json_str(const char *value) {
    putchar('"');
    if (value) {
        for (; *value; ++value) {
            unsigned char character = (unsigned char)*value;
            if (character == '"' || character == '\\') {
                putchar('\\');
                putchar(character);
            } else if (character >= 0x20 && character < 0x7f) {
                putchar(character);
            } else {
                printf("\\u%04x", character);
            }
        }
    }
    putchar('"');
}

static void xor_with_pin(char *data, int length, const char pin[6]) {
    int index;
    for (index = 0; index < length; ++index) {
        data[index] = (char)(data[index] ^ pin[index % 6]);
    }
}

static void redact_response(
    char *data, int length, const char *uid, const char pin[6]
) {
    int index;
    size_t uid_length = strlen(uid);
    for (index = 0; index + 12 <= length; ++index) {
        if (memcmp(data + index, "src=P", 5) == 0) {
            memset(data + index + 5, 'X', 7);
        }
    }
    if (uid_length > 0 && uid_length <= (size_t)length) {
        for (index = 0; index + (int)uid_length <= length; ++index) {
            if (memcmp(data + index, uid, uid_length) == 0) {
                memset(data + index, 'X', uid_length);
            }
        }
    }
    for (index = 0; index + 6 <= length; ++index) {
        if (memcmp(data + index, pin, 6) == 0) {
            memset(data + index, 'X', 6);
        }
    }
    for (index = 0; index < length; ++index) {
        unsigned char character = (unsigned char)data[index];
        if (character < 0x20 || character >= 0x7f) {
            data[index] = ' ';
        }
    }
    data[length] = 0;
}

static void print_ready(int connected, const char *stage, int code) {
    printf("{\"event\":\"ready\",\"connected\":%s,\"stage\":",
           connected ? "true" : "false");
    json_str(stage);
    printf(",\"code\":%d,\"safety\":{\"allowlisted_commands_only\":true,"
           "\"arbitrary_command_input\":false,\"gate_command_sent\":false,"
           "\"parameter_read_command_sent\":false,"
           "\"parameter_write_command_sent\":false}}\n", code);
    fflush(stdout);
}

static int valid_parameter_fragment(const char *fragment) {
    static const char field_ids[] = "123456789ABCDEFGHIJ";
    size_t field, index = 0, length = strlen(fragment);
    if (length < 4 || length > 768 || fragment[0] != ',') return 0;
    for (field = 0; field < sizeof(field_ids) - 1; ++field) {
        size_t value_start;
        if (fragment[index++] != ',' ||
            fragment[index++] != field_ids[field] ||
            fragment[index++] != ':') return 0;
        value_start = index;
        while (fragment[index] != 0 && fragment[index] != ',') {
            char c = fragment[index++];
            if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z')))
                return 0;
        }
        if (index == value_start) return 0;
    }
    return fragment[index] == 0;
}

static int send_exchange(
    int rdt_id,
    fn_rdt_write rdt_write,
    fn_rdt_read rdt_read,
    const char *uid,
    const char pin[6],
    const char *event,
    const char *pk_command,
    const char *expected_ack,
    int gate_command,
    int parameter_read,
    int parameter_write
) {
    char request[1200];
    char buffer[4096];
    char response[4097] = {0};
    int request_length = snprintf(
        request, sizeof(request),
        "{\"VER\":1,\"CMD\":\"UART\",\"ACT\":\"POST\",\"DATA\":{"
        "\"PKCMD\":\"%s;src=P9999999\\r\\n\"}}", pk_command
    );
    int write_code;
    int last_read_code = -10007;
    int response_received = 0;
    int response_bytes = 0;
    int transport_alive = 1;
    long deadline;

    if (request_length <= 0 || request_length >= (int)sizeof(request)) return 0;
    xor_with_pin(request, request_length, pin);
    write_code = rdt_write(rdt_id, request, request_length);
    memset(request, 0, sizeof(request));

    if (write_code >= 0) {
        deadline = monotonic_ms() + 5000;
        while (monotonic_ms() < deadline) {
            int read_code = rdt_read(rdt_id, buffer, sizeof(buffer) - 1, 500);
            last_read_code = read_code;
            if (read_code > 0) {
                int copy_length = read_code > (int)sizeof(response) - 1
                    ? (int)sizeof(response) - 1 : read_code;
                memcpy(response, buffer, copy_length);
                xor_with_pin(response, copy_length, pin);
                redact_response(response, copy_length, uid, pin);
                response_bytes += read_code;
                if (strstr(response, expected_ack) != NULL ||
                    strstr(response, "NAK ") != NULL) {
                    response_received = 1;
                    break;
                }
                memset(response, 0, sizeof(response));
            } else if (read_code < 0 && read_code != -10007) {
                transport_alive = 0;
                break;
            }
        }
    } else {
        transport_alive = 0;
    }

    printf("{\"event\":");
    json_str(event);
    printf(",\"write_code\":%d,\"request_sent\":%s,"
           "\"response_read_last_code\":%d,\"response_read_bytes\":%d,"
           "\"response_received\":%s,\"transport_alive\":%s,\"response\":",
           write_code, write_code >= 0 ? "true" : "false", last_read_code,
           response_bytes, response_received ? "true" : "false",
           transport_alive ? "true" : "false");
    if (response[0]) {
        json_str(response);
    } else {
        printf("null");
    }
    printf(",\"safety\":{\"rdt_write_called\":true,"
           "\"status_read_command_sent\":%s,\"gate_command_sent\":%s,"
           "\"parameter_read_command_sent\":%s,"
           "\"parameter_write_command_sent\":%s}}\n",
           strcmp(event, "status") == 0 && write_code >= 0 ? "true" : "false",
           gate_command && write_code >= 0 ? "true" : "false",
           parameter_read && write_code >= 0 ? "true" : "false",
           parameter_write && write_code >= 0 ? "true" : "false");
    fflush(stdout);
    return transport_alive;
}

int main(int argc, char **argv) {
    const char *iotc_library_path;
    const char *rdt_library_path;
    char uid_buffer[64] = {0};
    char pin[16] = {0};
    char command[1024];
    void *iotc_handle = NULL;
    void *rdt_handle = NULL;
    int sid = -1;
    int rdt_id = -1;
    int iotc_initialized = 0;
    int rdt_initialized = 0;
    int exit_code = 1;

    if (argc != 3) {
        fprintf(stderr, "usage: session-helper IOTC_LIB RDT_LIB\n");
        return 2;
    }
    iotc_library_path = argv[1];
    rdt_library_path = argv[2];
    if (!fgets(uid_buffer, sizeof(uid_buffer), stdin)) {
        fprintf(stderr, "missing uid\n");
        return 2;
    }
    uid_buffer[strcspn(uid_buffer, "\r\n")] = 0;
    if (strlen(uid_buffer) != 20) {
        fprintf(stderr, "invalid uid length\n");
        return 2;
    }
    if (!fgets(pin, sizeof(pin), stdin)) {
        fprintf(stderr, "missing pin\n");
        return 2;
    }
    pin[strcspn(pin, "\r\n")] = 0;
    if (strlen(pin) != 6 || strspn(pin, "0123456789") != 6) {
        fprintf(stderr, "invalid pin\n");
        return 2;
    }

    iotc_handle = dlopen(iotc_library_path, RTLD_NOW | RTLD_GLOBAL);
    if (!iotc_handle) {
        print_ready(0, "iotc_library", -1);
        goto cleanup;
    }
    rdt_handle = dlopen(rdt_library_path, RTLD_NOW | RTLD_GLOBAL);
    if (!rdt_handle) {
        print_ready(0, "rdt_library", -1);
        goto cleanup;
    }

#define IOTC_SYMBOL(type, name) type name = (type)dlsym(iotc_handle, #name)
    IOTC_SYMBOL(fn_iotc_init, IOTC_Initialize2);
    IOTC_SYMBOL(fn_get_sid, IOTC_Get_SessionID);
    IOTC_SYMBOL(fn_connect, IOTC_Connect_ByUID_Parallel);
    IOTC_SYMBOL(fn_session_close, IOTC_Session_Close);
    IOTC_SYMBOL(fn_deinit, IOTC_DeInitialize);
    IOTC_SYMBOL(fn_stop_sid, IOTC_Connect_Stop_BySID);
#undef IOTC_SYMBOL
#define RDT_SYMBOL(type, name) type name = (type)dlsym(rdt_handle, #name)
    RDT_SYMBOL(fn_rdt_init, RDT_Initialize);
    RDT_SYMBOL(fn_rdt_create, RDT_Create);
    RDT_SYMBOL(fn_rdt_write, RDT_Write);
    RDT_SYMBOL(fn_rdt_read, RDT_Read);
    RDT_SYMBOL(fn_rdt_destroy, RDT_Destroy);
    RDT_SYMBOL(fn_rdt_deinit, RDT_DeInitialize);
#undef RDT_SYMBOL

    if (!IOTC_Initialize2 || !IOTC_Get_SessionID ||
        !IOTC_Connect_ByUID_Parallel || !IOTC_Session_Close ||
        !IOTC_DeInitialize || !RDT_Initialize || !RDT_Create ||
        !RDT_Write || !RDT_Read || !RDT_Destroy || !RDT_DeInitialize) {
        print_ready(0, "symbols", -1);
        goto cleanup;
    }

    {
        int initialize_code = IOTC_Initialize2(0);
        if (initialize_code != 0 && initialize_code != -3) {
            print_ready(0, "iotc_initialize", initialize_code);
            goto cleanup;
        }
        iotc_initialized = 1;
    }
    sid = IOTC_Get_SessionID();
    if (sid < 0) {
        print_ready(0, "session_id", sid);
        goto cleanup;
    }

    {
        struct connect_ctx context = {
            IOTC_Connect_ByUID_Parallel, uid_buffer, sid, 0, 0
        };
        pthread_t thread;
        int thread_code = pthread_create(&thread, NULL, connect_worker, &context);
        if (thread_code != 0) {
            print_ready(0, "connect_thread", -99998);
            goto cleanup;
        }
        {
            long deadline = monotonic_ms() + 25000;
            while (!context.done && monotonic_ms() < deadline) {
                usleep(100000);
            }
        }
        if (!context.done) {
            if (IOTC_Connect_Stop_BySID) {
                IOTC_Connect_Stop_BySID(sid);
            }
            {
                long deadline = monotonic_ms() + 3000;
                while (!context.done && monotonic_ms() < deadline) {
                    usleep(100000);
                }
            }
        }
        if (!context.done) {
            print_ready(0, "iotc_connect_stuck", -13);
            fflush(stdout);
            _Exit(1);
        }
        pthread_join(thread, NULL);
        if (context.code < 0) {
            print_ready(0, "iotc_connect", context.code);
            goto cleanup;
        }
    }

    {
        int initialize_code = RDT_Initialize();
        if (initialize_code <= 0 && initialize_code != -10001) {
            print_ready(0, "rdt_initialize", initialize_code);
            goto cleanup;
        }
        rdt_initialized = 1;
    }
    rdt_id = RDT_Create(sid, 5000, 0);
    if (rdt_id < 0) {
        print_ready(0, "rdt_create", rdt_id);
        goto cleanup;
    }

    print_ready(1, "connected", 0);
    exit_code = 0;
    while (fgets(command, sizeof(command), stdin)) {
        command[strcspn(command, "\r\n")] = 0;
        if (strcmp(command, "QUIT") == 0) {
            break;
        }
        const char *event = NULL;
        const char *pk_command = NULL;
        const char *expected_ack = NULL;
        int gate_command = 0, parameter_read = 0, parameter_write = 0;
        if (strcmp(command, "STATUS") == 0) {
            event = "status"; pk_command = "READ STATUS"; expected_ack = "ACK STATUS";
        } else if (strcmp(command, "STATUS_RS") == 0) {
            event = "status"; pk_command = "RS"; expected_ack = "ACK RS";
        } else if (strcmp(command, "OPEN") == 0) {
            event = "command"; pk_command = "FULL OPEN"; expected_ack = "ACK FULL OPEN"; gate_command = 1;
        } else if (strcmp(command, "CLOSE") == 0) {
            event = "command"; pk_command = "FULL CLOSE"; expected_ack = "ACK FULL CLOSE"; gate_command = 1;
        } else if (strcmp(command, "STOP") == 0) {
            event = "command"; pk_command = "STOP"; expected_ack = "ACK STOP"; gate_command = 1;
        } else if (strcmp(command, "PED") == 0) {
            event = "command"; pk_command = "PED OPEN"; expected_ack = "ACK PED OPEN"; gate_command = 1;
        } else if (strcmp(command, "PARAM_READ") == 0) {
            event = "parameter_read"; pk_command = "READ FUNCTION"; expected_ack = "ACK READ FUNCTION"; parameter_read = 1;
        } else if (strncmp(command, "PARAM_WRITE ", 12) == 0 &&
                   valid_parameter_fragment(command + 12)) {
            static char write_command[800];
            snprintf(write_command, sizeof(write_command), "WRITE FUNCTION%s", command + 12);
            event = "parameter_write"; pk_command = write_command; expected_ack = "ACK FUNCTION"; parameter_write = 1;
        } else {
            printf("{\"event\":\"error\",\"error\":"
                   "\"unsupported_command\",\"transport_alive\":true}\n");
            fflush(stdout);
            continue;
        }
        if (!send_exchange(
                rdt_id, RDT_Write, RDT_Read, uid_buffer, pin, event,
                pk_command, expected_ack, gate_command, parameter_read,
                parameter_write
            )) {
            exit_code = 1;
            break;
        }
    }

cleanup:
    memset(pin, 0, sizeof(pin));
    if (rdt_id >= 0 && rdt_handle) {
        fn_rdt_destroy destroy = (fn_rdt_destroy)dlsym(rdt_handle, "RDT_Destroy");
        if (destroy) destroy(rdt_id);
    }
    if (sid >= 0 && iotc_handle) {
        fn_session_close close_session =
            (fn_session_close)dlsym(iotc_handle, "IOTC_Session_Close");
        if (close_session) close_session(sid);
    }
    if (rdt_initialized && rdt_handle) {
        fn_rdt_deinit deinitialize =
            (fn_rdt_deinit)dlsym(rdt_handle, "RDT_DeInitialize");
        if (deinitialize) deinitialize();
    }
    if (iotc_initialized && iotc_handle) {
        fn_deinit deinitialize =
            (fn_deinit)dlsym(iotc_handle, "IOTC_DeInitialize");
        if (deinitialize) deinitialize();
    }
    if (rdt_handle) dlclose(rdt_handle);
    if (iotc_handle) dlclose(iotc_handle);
    return exit_code;
}
