#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef int (*fn_iotc_init)(unsigned short);
typedef void (*fn_iotc_version)(unsigned int *);
typedef int (*fn_get_sid)(void);
typedef int (*fn_connect)(const char *, int);
typedef void (*fn_session_close)(int);
typedef int (*fn_deinit)(void);
typedef int (*fn_stop_sid)(int);
typedef int (*fn_rdt_version)(void);
typedef int (*fn_rdt_init)(void);
typedef int (*fn_rdt_create)(int, int, unsigned char);
typedef int (*fn_rdt_read)(int, char *, int, int);
typedef int (*fn_rdt_destroy)(int);
typedef int (*fn_rdt_deinit)(void);

struct connect_ctx { fn_connect fn; const char *uid; int sid; volatile int done; int code; };
static void *connect_worker(void *p) {
    struct connect_ctx *c = (struct connect_ctx *)p;
    c->code = c->fn(c->uid, c->sid);
    c->done = 1;
    return NULL;
}

static long monotonic_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

static void json_str(const char *s) {
    putchar('"');
    if (s) {
        for (; *s; ++s) {
            unsigned char c = (unsigned char)*s;
            if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
            else if (c >= 0x20 && c < 0x7f) putchar(c);
            else printf("\\u%04x", c);
        }
    }
    putchar('"');
}

static const char *iotc_name(int code) {
    switch (code) {
        case -1: return "IOTC_ER_SERVER_NOT_RESPONSE"; case -2: return "IOTC_ER_FAIL_RESOLVE_HOSTNAME";
        case -3: return "IOTC_ER_ALREADY_INITIALIZED"; case -10: return "IOTC_ER_UNLICENSE";
        case -12: return "IOTC_ER_NOT_INITIALIZED"; case -13: return "IOTC_ER_TIMEOUT";
        case -14: return "IOTC_ER_INVALID_SID"; case -15: return "IOTC_ER_UNKNOWN_DEVICE";
        case -18: return "IOTC_ER_EXCEED_MAX_SESSION"; case -19: return "IOTC_ER_CAN_NOT_FIND_DEVICE";
        case -20: return "IOTC_ER_CONNECT_IS_CALLING"; case -22: return "IOTC_ER_SESSION_CLOSE_BY_REMOTE";
        case -23: return "IOTC_ER_REMOTE_TIMEOUT_DISCONNECT"; case -24: return "IOTC_ER_DEVICE_NOT_LISTENING";
        case -27: return "IOTC_ER_FAIL_CONNECT_SEARCH"; case -32: return "IOTC_ER_TCP_TRAVEL_FAILED";
        case -33: return "IOTC_ER_TCP_CONNECT_TO_SERVER_FAILED"; case -40: return "IOTC_ER_NO_PERMISSION";
        case -41: return "IOTC_ER_NETWORK_UNREACHABLE"; case -42: return "IOTC_ER_FAIL_SETUP_RELAY";
        case -43: return "IOTC_ER_NOT_SUPPORT_RELAY"; case -44: return "IOTC_ER_NO_SERVER_LIST";
        case -46: return "IOTC_ER_INVALID_ARG"; case -50: return "IOTC_ER_SESSION_CLOSED";
        case -60: return "IOTC_ER_MASTER_NOT_RESPONSE"; case -90: return "IOTC_ER_DEVICE_OFFLINE";
        case -1004: return "TUTK_ER_INVALID_LICENSE_KEY"; case -1005: return "TUTK_ER_NO_LICENSE_KEY";
        default: return code >= 0 ? "success" : "unknown_error";
    }
}
static const char *rdt_name(int code) {
    switch (code) {
        case -10000: return "RDT_ER_NOT_INITIALIZED"; case -10001: return "RDT_ER_ALREADY_INITIALIZED";
        case -10002: return "RDT_ER_EXCEED_MAX_CHANNEL"; case -10003: return "RDT_ER_MEM_INSUFF";
        case -10004: return "RDT_ER_FAIL_CREATE_THREAD"; case -10005: return "RDT_ER_FAIL_CREATE_MUTEX";
        case -10006: return "RDT_ER_RDT_DESTROYED"; case -10007: return "RDT_ER_TIMEOUT";
        case -10008: return "RDT_ER_INVALID_RDT_ID"; case -10009: return "RDT_ER_RCV_DATA_END";
        case -10010: return "RDT_ER_REMOTE_ABORT"; case -10011: return "RDT_ER_LOCAL_ABORT";
        case -10012: return "RDT_ER_CHANNEL_OCCUPIED"; case -10013: return "RDT_ER_NO_PERMISSION";
        case -10014: return "RDT_ER_INVALID_ARG"; default: return code >= 0 ? "success" : "unknown_error";
    }
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: helper IOTC_LIB RDT_LIB\n"); return 2; }
    const char *iotc_libpath = argv[1];
    const char *rdt_libpath = argv[2];
    char uidbuf[64] = {0};
    if (!fgets(uidbuf, sizeof(uidbuf), stdin)) { fprintf(stderr, "missing uid\n"); return 2; }
    uidbuf[strcspn(uidbuf, "\r\n")] = 0;
    const char *uid = uidbuf;
    if (strlen(uid) != 20) { fprintf(stderr, "invalid uid length\n"); return 2; }

    int iotc_library_loaded=0, rdt_library_loaded=0, iotc_init_code=0, iotc_init_set=0, sid=-1, connect_attempted=0, connect_code=0, connect_set=0;
    int connect_timeout=0, connect_stop_code=0, stop_set=0, worker_stuck=0, iotc_connected=0;
    unsigned int iotc_version=0; int iotc_version_set=0;
    int rdt_version=0, rdt_version_set=0;
    int rdt_init_code=0, rdt_init_set=0, rdt_create_attempted=0, rdt_id=-1, rdt_connected=0;
    int passive_attempted=0, passive_count=0, passive_bytes=0, passive_last=0, passive_last_set=0;
    int close_called=0, rdt_destroy_code=0, rdt_destroy_set=0, rdt_deinit_code=0, rdt_deinit_set=0, iotc_deinit_code=0, iotc_deinit_set=0;
    char library_error[512] = {0};

    void *iotc_h = dlopen(iotc_libpath, RTLD_NOW | RTLD_GLOBAL);
    if (!iotc_h) { const char *e = dlerror(); snprintf(library_error, sizeof(library_error), "IOTC: %s", e ? e : "dlopen_failed"); }
    else iotc_library_loaded=1;
    void *rdt_h = NULL;
    if (iotc_h) {
        rdt_h = dlopen(rdt_libpath, RTLD_NOW | RTLD_GLOBAL);
        if (!rdt_h) { const char *e = dlerror(); snprintf(library_error, sizeof(library_error), "RDT: %s", e ? e : "dlopen_failed"); }
        else rdt_library_loaded=1;
    }

#define IOTC_SYM(type,name) type name = iotc_h ? (type)dlsym(iotc_h, #name) : NULL
    IOTC_SYM(fn_iotc_init, IOTC_Initialize2); IOTC_SYM(fn_iotc_version, IOTC_Get_Version);
    IOTC_SYM(fn_get_sid, IOTC_Get_SessionID); IOTC_SYM(fn_connect, IOTC_Connect_ByUID_Parallel);
    IOTC_SYM(fn_session_close, IOTC_Session_Close); IOTC_SYM(fn_deinit, IOTC_DeInitialize);
    IOTC_SYM(fn_stop_sid, IOTC_Connect_Stop_BySID);
#undef IOTC_SYM
#define RDT_SYM(type,name) type name = rdt_h ? (type)dlsym(rdt_h, #name) : NULL
    RDT_SYM(fn_rdt_version, RDT_GetRDTApiVer); RDT_SYM(fn_rdt_init, RDT_Initialize);
    RDT_SYM(fn_rdt_create, RDT_Create); RDT_SYM(fn_rdt_read, RDT_Read);
    RDT_SYM(fn_rdt_destroy, RDT_Destroy); RDT_SYM(fn_rdt_deinit, RDT_DeInitialize);
#undef RDT_SYM
    void *TUTK_SDK_Set_License_Key = iotc_h ? dlsym(iotc_h, "TUTK_SDK_Set_License_Key") : NULL;

    int required_ok = IOTC_Initialize2 && IOTC_Get_SessionID && IOTC_Connect_ByUID_Parallel && IOTC_Session_Close && IOTC_DeInitialize;
    if (iotc_library_loaded && !required_ok) snprintf(library_error, sizeof(library_error), "required_iotc_symbols_missing");

    if (IOTC_Get_Version) { IOTC_Get_Version(&iotc_version); iotc_version_set=1; }
    if (RDT_GetRDTApiVer) { rdt_version=RDT_GetRDTApiVer(); rdt_version_set=1; }

    int iotc_initialized=0, rdt_initialized=0;
    if (iotc_library_loaded && required_ok) {
        iotc_init_code = IOTC_Initialize2(0); iotc_init_set=1;
        if (iotc_init_code == 0 || iotc_init_code == -3) {
            iotc_initialized=1; sid=IOTC_Get_SessionID();
            if (sid >= 0) {
                connect_attempted=1;
                struct connect_ctx ctx = { IOTC_Connect_ByUID_Parallel, uid, sid, 0, 0 };
                pthread_t th; int trc=pthread_create(&th, NULL, connect_worker, &ctx);
                if (trc == 0) {
                    long deadline=monotonic_ms()+25000;
                    while (!ctx.done && monotonic_ms() < deadline) usleep(100000);
                    if (!ctx.done) {
                        connect_timeout=1;
                        if (IOTC_Connect_Stop_BySID) { connect_stop_code=IOTC_Connect_Stop_BySID(sid); stop_set=1; }
                        long grace=monotonic_ms()+3000;
                        while (!ctx.done && monotonic_ms() < grace) usleep(100000);
                    }
                    if (ctx.done) { connect_code=ctx.code; connect_set=1; pthread_join(th,NULL); }
                    else worker_stuck=1;
                } else { connect_code=-99998; connect_set=1; }
                if (connect_set && connect_code >= 0) iotc_connected=1;
            } else { connect_code=sid; connect_set=1; }
        }
    }

    if (!worker_stuck && iotc_connected && rdt_library_loaded && RDT_Initialize && RDT_Create && RDT_Read && RDT_Destroy && RDT_DeInitialize) {
        rdt_init_code=RDT_Initialize(); rdt_init_set=1;
        if (rdt_init_code > 0 || rdt_init_code == -10001) {
            rdt_initialized=1; rdt_create_attempted=1; rdt_id=RDT_Create(sid,5000,0);
            if (rdt_id >= 0) {
                rdt_connected=1; passive_attempted=1; char buf[4096]; long deadline=monotonic_ms()+2000;
                while (monotonic_ms() < deadline) {
                    int ret=RDT_Read(rdt_id,buf,sizeof(buf),300); passive_last=ret; passive_last_set=1;
                    if (ret>0) { passive_count++; passive_bytes += ret; }
                    else if (ret<0 && ret!=-10007) break;
                }
            }
        }
    }

    if (!worker_stuck && rdt_id>=0 && RDT_Destroy) { rdt_destroy_code=RDT_Destroy(rdt_id); rdt_destroy_set=1; }
    if (!worker_stuck && sid>=0 && IOTC_Session_Close) { IOTC_Session_Close(sid); close_called=1; }
    if (!worker_stuck && rdt_initialized && RDT_DeInitialize) { rdt_deinit_code=RDT_DeInitialize(); rdt_deinit_set=1; }
    if (!worker_stuck && iotc_initialized && IOTC_DeInitialize) { iotc_deinit_code=IOTC_DeInitialize(); iotc_deinit_set=1; }

    printf("{");
    printf("\"library_loaded\":%s,\"iotc_library_loaded\":%s,\"rdt_library_loaded\":%s,\"library_error\":",(iotc_library_loaded&&rdt_library_loaded)?"true":"false",iotc_library_loaded?"true":"false",rdt_library_loaded?"true":"false"); if(library_error[0])json_str(library_error);else printf("null");
    printf(",\"iotc_version\":"); if(iotc_version_set)printf("\"0x%08x\"",iotc_version);else printf("null");
    printf(",\"rdt_version\":"); if(rdt_version_set)printf("\"0x%08x\"",(unsigned int)rdt_version);else printf("null");
    printf(",\"symbols\":{\"IOTC_Initialize2\":%s,\"IOTC_Get_Version\":%s,\"IOTC_Get_SessionID\":%s,\"IOTC_Connect_ByUID_Parallel\":%s,\"IOTC_Session_Close\":%s,\"IOTC_DeInitialize\":%s,\"IOTC_Connect_Stop_BySID\":%s,\"RDT_GetRDTApiVer\":%s,\"RDT_Initialize\":%s,\"RDT_Create\":%s,\"RDT_Read\":%s,\"RDT_Destroy\":%s,\"RDT_DeInitialize\":%s,\"TUTK_SDK_Set_License_Key\":%s}",
      IOTC_Initialize2?"true":"false",IOTC_Get_Version?"true":"false",IOTC_Get_SessionID?"true":"false",IOTC_Connect_ByUID_Parallel?"true":"false",IOTC_Session_Close?"true":"false",IOTC_DeInitialize?"true":"false",IOTC_Connect_Stop_BySID?"true":"false",RDT_GetRDTApiVer?"true":"false",RDT_Initialize?"true":"false",RDT_Create?"true":"false",RDT_Read?"true":"false",RDT_Destroy?"true":"false",RDT_DeInitialize?"true":"false",TUTK_SDK_Set_License_Key?"true":"false");
#define NULINT(key,set,val) do{printf(",\"%s\":",key); if(set) printf("%d",val); else printf("null");}while(0)
    NULINT("iotc_initialize_code",iotc_init_set,iotc_init_code); printf(",\"iotc_initialize_name\":"); if(iotc_init_set)json_str(iotc_name(iotc_init_code));else printf("null");
    printf(",\"session_id_allocated\":%s,\"iotc_connect_attempted\":%s",sid>=0?"true":"false",connect_attempted?"true":"false");
    NULINT("iotc_connect_code",connect_set,connect_code); printf(",\"iotc_connect_name\":"); if(connect_set)json_str(iotc_name(connect_code));else printf("null");
    printf(",\"iotc_connect_timed_out\":%s",connect_timeout?"true":"false"); NULINT("iotc_connect_stop_code",stop_set,connect_stop_code); printf(",\"connect_worker_stuck\":%s,\"iotc_connected\":%s",worker_stuck?"true":"false",iotc_connected?"true":"false");
    NULINT("rdt_initialize_code",rdt_init_set,rdt_init_code); printf(",\"rdt_initialize_name\":"); if(rdt_init_set)json_str(rdt_name(rdt_init_code));else printf("null");
    printf(",\"rdt_create_attempted\":%s",rdt_create_attempted?"true":"false"); NULINT("rdt_create_code",rdt_create_attempted,rdt_id); printf(",\"rdt_create_name\":"); if(rdt_create_attempted)json_str(rdt_name(rdt_id));else printf("null");
    printf(",\"rdt_connected\":%s,\"passive_read_attempted\":%s,\"passive_read_count\":%d,\"passive_read_bytes\":%d",rdt_connected?"true":"false",passive_attempted?"true":"false",passive_count,passive_bytes); NULINT("passive_read_last_code",passive_last_set,passive_last);
    printf(",\"cleanup\":{"); int first=1;
#define CLEAN(key,set,val) do{if(set){if(!first)putchar(',');json_str(key);printf(":%d",val);first=0;}}while(0)
    CLEAN("rdt_destroy_code",rdt_destroy_set,rdt_destroy_code); if(close_called){if(!first)putchar(',');json_str("iotc_session_close_called");printf(":true");first=0;} CLEAN("rdt_deinitialize_code",rdt_deinit_set,rdt_deinit_code); CLEAN("iotc_deinitialize_code",iotc_deinit_set,iotc_deinit_code);
    printf("},\"safety\":{\"rdt_write_bound\":false,\"rdt_write_called\":false,\"application_payload_written\":false,\"gate_command_sent\":false}}");
    putchar('\n');
    fflush(stdout);
    if (worker_stuck) _Exit(0);
    if(rdt_h)dlclose(rdt_h);
    if(iotc_h)dlclose(iotc_h);
    return 0;
}
