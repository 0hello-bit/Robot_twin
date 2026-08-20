/**
  ******************************************************************************
  * @file    Project/STM32F10x_StdPeriph_Template/stm32f10x_it.c 
  * @author  MCD Application Team
  * @version V3.5.0
  * @date    08-April-2011
  * @brief   Main Interrupt Service Routines.
  *          This file provides template for all exceptions handler and 
  *          peripherals interrupt service routine.
  ******************************************************************************
  * @attention
  *
  * THE PRESENT FIRMWARE WHICH IS FOR GUIDANCE ONLY AIMS AT PROVIDING CUSTOMERS
  * WITH CODING INFORMATION REGARDING THEIR PRODUCTS IN ORDER FOR THEM TO SAVE
  * TIME. AS A RESULT, STMICROELECTRONICS SHALL NOT BE HELD LIABLE FOR ANY
  * DIRECT, INDIRECT OR CONSEQUENTIAL DAMAGES WITH RESPECT TO ANY CLAIMS ARISING
  * FROM THE CONTENT OF SUCH FIRMWARE AND/OR THE USE MADE BY CUSTOMERS OF THE
  * CODING INFORMATION CONTAINED HEREIN IN CONNECTION WITH THEIR PRODUCTS.
  *
  * <h2><center>&copy; COPYRIGHT 2011 STMicroelectronics</center></h2>
  ******************************************************************************
  */

/* Includes ------------------------------------------------------------------*/
#include "stm32f10x_it.h"
#include "uart_ring.h"
#include "mono_time.h"

/* SPSC UART RX ring — shared between USART1_IRQHandler (producer) and
   the main loop (consumer).  Defined in main.c. */
extern UartRing g_uart_ring;
/* SPSC UART TX ring — shared between the main loop (producer) and
   USART1_IRQHandler (consumer, TXE interrupt).  Defined in main.c. */
extern UartRing g_uart_tx_ring;

/** @addtogroup STM32F10x_StdPeriph_Template
  * @{
  */

/* Private typedef -----------------------------------------------------------*/
/* Private define ------------------------------------------------------------*/
/* Private macro -------------------------------------------------------------*/
/* Private variables ---------------------------------------------------------*/
/* Private function prototypes -----------------------------------------------*/
/* Private functions ---------------------------------------------------------*/

/******************************************************************************/
/*            Cortex-M3 Processor Exceptions Handlers                         */
/******************************************************************************/

/**
  * @brief  This function handles NMI exception.
  * @param  None
  * @retval None
  */
void NMI_Handler(void)
{
}

/**
  * @brief  This function handles Hard Fault exception.
  * @param  None
  * @retval None
  */
void HardFault_Handler(void)
{
  /* Go to infinite loop when Hard Fault exception occurs */
  while (1)
  {
  }
}

/**
  * @brief  This function handles Memory Manage exception.
  * @param  None
  * @retval None
  */
void MemManage_Handler(void)
{
  /* Go to infinite loop when Memory Manage exception occurs */
  while (1)
  {
  }
}

/**
  * @brief  This function handles Bus Fault exception.
  * @param  None
  * @retval None
  */
void BusFault_Handler(void)
{
  /* Go to infinite loop when Bus Fault exception occurs */
  while (1)
  {
  }
}

/**
  * @brief  This function handles Usage Fault exception.
  * @param  None
  * @retval None
  */
void UsageFault_Handler(void)
{
  /* Go to infinite loop when Usage Fault exception occurs */
  while (1)
  {
  }
}

/**
  * @brief  This function handles SVCall exception.
  * @param  None
  * @retval None
  */
void SVC_Handler(void)
{
}

/**
  * @brief  This function handles Debug Monitor exception.
  * @param  None
  * @retval None
  */
void DebugMon_Handler(void)
{
}

/**
  * @brief  This function handles PendSVC exception.
  * @param  None
  * @retval None
  */
void PendSV_Handler(void)
{
}

/**
  * @brief  This function handles SysTick Handler.
  * @param  None
  * @retval None
  */
void SysTick_Handler(void)
{
}

/**
  * @brief  USART1 RX interrupt — feeds the SPSC ring buffer.
  *         Reads DR (which clears RXNE and also clears ORE when SR
  *         was read first), increments observable counters.
  *         No protocol parsing is performed inside the ISR.
  * @param  None
  * @retval None
  */
void USART1_IRQHandler(void)
{
    uint8_t byte;

    if (USART_GetITStatus(USART1, USART_IT_RXNE) != RESET) {
        /* Check overrun error before reading DR.
           Reading SR (via GetFlagStatus) then DR clears ORE. */
        if (USART_GetFlagStatus(USART1, USART_FLAG_ORE) != RESET) {
            g_uart_ring.ore_events++;
        }

        byte = (uint8_t)USART_ReceiveData(USART1);
        /* Capture the software UART-ISR boundary before the byte can wait in
           the ring.  This is intentionally not called wire/hardware time. */
        uart_ring_push_at(&g_uart_ring, byte, mono_now_ms());
    }

    /* Task 4B-4 fix: TXE interrupt drains the TX ring (non-blocking TX).
       When the ring empties, disable TXE so the interrupt stops firing.
       The main loop enables TXE via uart_tx_sink() when it pushes bytes. */
    if (USART_GetITStatus(USART1, USART_IT_TXE) != RESET) {
        if (uart_ring_pop(&g_uart_tx_ring, &byte)) {
            USART_SendData(USART1, byte);
        } else {
            USART_ITConfig(USART1, USART_IT_TXE, DISABLE);
        }
    }
}

/******************************************************************************/
/*                 STM32F10x Peripherals Interrupt Handlers                   */
/*  Add here the Interrupt Handler for the used peripheral(s) (PPP), for the  */
/*  available peripheral interrupt handler's name please refer to the startup */
/*  file (startup_stm32f10x_xx.s).                                            */
/******************************************************************************/

/**
  * @brief  This function handles PPP interrupt request.
  * @param  None
  * @retval None
  */
/*void PPP_IRQHandler(void)
{
}*/

/**
  * @}
  */ 


/******************* (C) COPYRIGHT 2011 STMicroelectronics *****END OF FILE****/
