#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "twin_control_protocol.h"

static const TwinControlParams k_baseline = {
    35.0F, 0.0F, 10.0F, 680, 1U, "baseline"
};

static TwinControlParams g_active;

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

static int decode_hex(const char *text, unsigned char *output, unsigned int *length)
{
    unsigned int count = 0U;
    while (*text != '\0' && *text != '\n' && *text != '\r') {
        int high;
        int low;
        if (text[1] == '\0' || text[1] == '\n' || text[1] == '\r' ||
            count >= TWIN_CONTROL_LINE_MAX + 8U) return 0;
        high = hex_value(text[0]);
        low = hex_value(text[1]);
        if (high < 0 || low < 0) return 0;
        output[count++] = (unsigned char)((high << 4) | low);
        text += 2;
    }
    *length = count;
    return 1;
}

static void write_hex(const char *text, unsigned int length)
{
    static const char hex[] = "0123456789ABCDEF";
    unsigned int index;
    for (index = 0U; index < length; ++index) {
        unsigned char byte = (unsigned char)text[index];
        putchar(hex[(byte >> 4) & 0x0FU]);
        putchar(hex[byte & 0x0FU]);
    }
}

static void emit(char operation, const TwinControlResult *result)
{
    TwinControlResult empty;
    char ack[TWIN_CONTROL_LINE_MAX];
    uint16_t ack_length;
    if (result == 0) {
        memset(&empty, 0, sizeof(empty));
        result = &empty;
    }
    ack_length = twin_control_encode_ack(result, ack, sizeof(ack));
    printf("O,%c,%u,%u,%u,%lu,%s,%s,%.9g,%.9g,%.9g,%d,%lu,%s,",
           operation,
           (unsigned int)result->has_ack,
           (unsigned int)result->applied,
           (unsigned int)twin_control_motion_inhibited(),
           (unsigned long)result->version,
           result->campaign_id,
           result->reason,
           (double)g_active.kp,
           (double)g_active.ki,
           (double)g_active.kd,
           (int)g_active.speed_max,
           (unsigned long)g_active.version,
           g_active.campaign_id);
    write_hex(ack, ack_length);
    putchar('\n');
    fflush(stdout);
}

static int receive_hex(const char *text)
{
    unsigned char bytes[TWIN_CONTROL_LINE_MAX + 8U];
    unsigned int length;
    unsigned int index;
    TwinControlResult latest;
    if (!decode_hex(text, bytes, &length)) return 0;
    memset(&latest, 0, sizeof(latest));
    for (index = 0U; index < length; ++index) {
        TwinControlResult result;
        if (twin_control_receive_byte(bytes[index], &result)) latest = result;
    }
    emit('X', &latest);
    return 1;
}

int main(void)
{
    char line[2U * (TWIN_CONTROL_LINE_MAX + 8U) + 4U];
    g_active = k_baseline;
    twin_control_init(&k_baseline);
    while (fgets(line, sizeof(line), stdin) != 0) {
        if (strcmp(line, "I\n") == 0 || strcmp(line, "I\r\n") == 0) {
            g_active = k_baseline;
            twin_control_init(&k_baseline);
            emit('I', 0);
        } else if (strncmp(line, "X ", 2U) == 0) {
            if (!receive_hex(line + 2U)) {
                fputs("invalid hexadecimal trace command\n", stderr);
                return 2;
            }
        } else if (strcmp(line, "A\n") == 0 || strcmp(line, "A\r\n") == 0) {
            TwinControlResult result;
            (void)twin_control_apply_pending(&g_active, &k_baseline, &result);
            emit('A', &result);
        } else if (strcmp(line, "T\n") == 0 || strcmp(line, "T\r\n") == 0) {
            twin_control_timeout();
            emit('T', 0);
        } else if (strcmp(line, "Q\n") == 0 || strcmp(line, "Q\r\n") == 0) {
            emit('Q', 0);
        } else {
            fputs("unknown trace command\n", stderr);
            return 2;
        }
    }
    return 0;
}
